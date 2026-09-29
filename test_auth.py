"""
Who may call /parse-recipe (auth.py). Run: .venv/bin/python -m pytest -q

Tokens are signed here with a generated ES256 key standing in for the app
project's, and Supabase is faked, so nothing touches the network.
"""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import app as worker
from auth import AuthError, RateLimiter, TokenVerifier

URL = "https://qaekljlqmqojdtuqofwb.supabase.co"
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
JWK = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
JWK.update({"kid": "key-1", "alg": "ES256", "use": "sig"})


def token(**overrides) -> str:
    claims = {
        "sub": "user-1",
        "aud": "authenticated",
        "iss": f"{URL}/auth/v1",
        "exp": int(time.time()) + 3600,
        "is_anonymous": False,
    }
    claims.update(overrides)
    kid = claims.pop("kid", "key-1")
    return jwt.encode(claims, PRIVATE_KEY, algorithm="ES256", headers={"kid": kid})


class FakeSupabase:
    """The JWKS and /auth/v1/user endpoints; records each call."""

    def __init__(self, users: dict[str, dict] | None = None) -> None:
        self.users = users or {}
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict | None = None) -> dict:
        self.calls.append(url)
        if url.endswith("/.well-known/jwks.json"):
            return {"keys": [JWK]}
        if url.endswith("/auth/v1/user"):
            bearer = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
            if bearer in self.users:
                return self.users[bearer]
            raise HTTPError(url, 401, "unauthorized", {}, None)
        raise AssertionError(url)


def verifier(fake: FakeSupabase | None = None) -> TokenVerifier:
    return TokenVerifier(supabase_url=URL, anon_key="anon", fetch_json=fake or FakeSupabase())


class TestTokenVerifier:
    def test_a_token_signed_with_the_project_key_passes(self):
        fake = FakeSupabase()
        v = verifier(fake)

        caller = v.verify(token(sub="abc", is_anonymous=True))
        v.verify(token())

        assert caller.user_id == "abc"
        assert caller.is_anonymous is True
        assert fake.calls == [f"{URL}/auth/v1/.well-known/jwks.json"], "keys cached"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"exp": int(time.time()) - 10},
            {"aud": "anon"},
            {"iss": "https://npjuylxjgaiualfihxpt.supabase.co/auth/v1"},
        ],
        ids=["expired", "wrong audience", "other project"],
    )
    def test_bad_claims_are_refused(self, overrides):
        with pytest.raises(AuthError):
            verifier().verify(token(**overrides))

    def test_another_key_is_refused(self):
        other = ec.generate_private_key(ec.SECP256R1())
        forged = jwt.encode(
            {"sub": "x", "aud": "authenticated", "iss": f"{URL}/auth/v1",
             "exp": int(time.time()) + 60},
            other, algorithm="ES256", headers={"kid": "key-1"},
        )
        with pytest.raises(AuthError):
            verifier().verify(forged)

    def test_garbage_is_refused(self):
        with pytest.raises(AuthError):
            verifier().verify("not-a-token")

    def test_a_legacy_hs256_token_is_checked_with_supabase(self):
        legacy = jwt.encode({"sub": "old", "aud": "authenticated"}, "legacy-shared-secret-32-bytes-long!", algorithm="HS256")
        fake = FakeSupabase(users={legacy: {"id": "old", "is_anonymous": False}})

        caller = verifier(fake).verify(legacy)

        assert caller.user_id == "old"
        assert fake.calls == [f"{URL}/auth/v1/user"]

    def test_a_token_supabase_does_not_know_is_refused(self):
        legacy = jwt.encode({"sub": "gone"}, "legacy-shared-secret-32-bytes-long!", algorithm="HS256")
        with pytest.raises(AuthError):
            verifier().verify(legacy)

    def test_an_unknown_kid_falls_back_to_supabase(self):
        rotated = token(kid="key-2")
        fake = FakeSupabase(users={rotated: {"id": "user-1"}})

        assert verifier(fake).verify(rotated).user_id == "user-1"


class TestRateLimiter:
    def test_hourly_and_daily_limits(self):
        now = [0.0]
        limiter = RateLimiter([(2, 3600.0), (3, 86400.0)], clock=lambda: now[0])

        assert limiter.allow("u") and limiter.allow("u")
        assert not limiter.allow("u"), "third in the hour"
        assert limiter.allow("someone-else"), "per user"

        now[0] = 3601.0
        assert limiter.allow("u"), "a new hour"
        assert not limiter.allow("u"), "but three today"

        now[0] = 86401.0 + 3600
        assert limiter.allow("u"), "a new day"


class TestEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(worker, "verifier", verifier())
        monkeypatch.setattr(worker, "user_limits", RateLimiter([(2, 3600.0)]))
        return TestClient(worker.app)

    def post(self, client, text="", bearer=None):
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        return client.post("/parse-recipe", json={"text": text or " "}, headers=headers)

    def test_health_stays_open(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_no_token_is_401(self, client):
        response = self.post(client)
        assert response.status_code == 401
        assert response.json()["detail"] == "Sign in to convert recipes."

    def test_a_bad_token_is_401(self, client):
        assert self.post(client, bearer="nope").status_code == 401

    def test_a_signed_in_caller_gets_through(self, client):
        # Empty text: past auth, stopped before any food search.
        response = self.post(client, bearer=token())
        assert response.status_code == 422
        assert response.json()["detail"] == "Recipe text is empty."

    def test_over_the_limit_is_429(self, client):
        for _ in range(2):
            assert self.post(client, bearer=token()).status_code == 422
        response = self.post(client, bearer=token())
        assert response.status_code == 429
        assert "Try again in an hour" in response.json()["detail"]

    def test_too_long_is_413(self, client):
        response = self.post(client, text="x" * 10_001, bearer=token())
        assert response.status_code == 413

    def test_too_many_ingredients_is_413(self, client):
        text = "\n".join(f"1 cup ingredient {i}" for i in range(61))
        response = self.post(client, text=text, bearer=token())
        assert response.status_code == 413
        assert "more than 60 ingredients" in response.json()["detail"]
