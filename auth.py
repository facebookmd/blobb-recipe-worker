"""
Who may call /parse-recipe, and how often.

Every conversion runs several food searches against Supabase, so an open
endpoint let anyone with the URL run up the bill. A request now needs the
caller's Supabase session token from the *app* project (qaekljlqmqojdtuqofwb,
not the USDA project the matcher reads food from), and each user gets a
limited number of conversions.

Tokens signed with one of the project's published keys (ES256, from its JWKS)
are checked here, with no network call once the keys are cached. Anything
else (the legacy shared-secret HS256 signing, or a key published after the
cache was filled) is checked by asking Supabase Auth who the token belongs to,
so a key rotation cannot lock everyone out.

Anonymous users (the app signs everyone in anonymously until they connect
Google or Apple) may convert too. Making throwaway users is held back by
Supabase's own per-IP limit on anonymous sign-ins; the per-user limits below
and the service's instance cap bound the rest.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt

APP_SUPABASE_URL = os.environ.get(
    "APP_SUPABASE_URL", "https://qaekljlqmqojdtuqofwb.supabase.co"
).rstrip("/")

# The app project's public client key: what the app itself ships with. Only
# used for the Supabase Auth fallback check.
APP_SUPABASE_ANON_KEY = os.environ.get(
    "APP_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFh"
    "ZWtsamxxbXFvamR0dXFvZndiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY1MTY2MzksImV4"
    "cCI6MjEwMjA5MjYzOX0.iXepQ9ASYwbADDQ-yC6lU2LZ3TTYcAkW2S_BuJFIk-I",
)

JWKS_TTL_SECONDS = 3600
HTTP_TIMEOUT_SECONDS = 10


class AuthError(Exception):
    """The token is missing, malformed, expired, or not the app's."""


@dataclass(frozen=True)
class Caller:
    user_id: str
    is_anonymous: bool


def _fetch_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class TokenVerifier:
    """Checks app-project session tokens; see the module docstring."""

    def __init__(
        self,
        supabase_url: str = APP_SUPABASE_URL,
        anon_key: str = APP_SUPABASE_ANON_KEY,
        fetch_json: Callable[..., dict] = _fetch_json,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = supabase_url
        self._anon_key = anon_key
        self._fetch_json = fetch_json
        self._clock = clock
        self._issuer = f"{supabase_url}/auth/v1"
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_at = float("-inf")
        self._lock = threading.Lock()

    def verify(self, token: str) -> Caller:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise AuthError("Malformed token.") from error

        key = self._key(header.get("kid")) if header.get("alg") == "ES256" else None
        if key is None:
            return self._ask_supabase(token)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer=self._issuer,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError(f"Invalid token: {error}") from error
        return Caller(
            user_id=str(claims["sub"]),
            is_anonymous=bool(claims.get("is_anonymous")),
        )

    def _key(self, kid: str | None) -> jwt.PyJWK | None:
        if not kid:
            return None
        with self._lock:
            stale = self._clock() - self._keys_at > JWKS_TTL_SECONDS
            if stale or kid not in self._keys:
                # Refetch at most once a minute for unknown kids, so garbage
                # kids cannot turn every request into a fetch.
                if stale or self._clock() - self._keys_at > 60:
                    self._refresh_keys()
            return self._keys.get(kid)

    def _refresh_keys(self) -> None:
        try:
            body = self._fetch_json(f"{self._url}/auth/v1/.well-known/jwks.json")
        except (HTTPError, URLError, TimeoutError, ValueError):
            return  # keep what we had; unknown kids fall back to Supabase
        keys = {}
        for raw in body.get("keys", []):
            try:
                keys[raw["kid"]] = jwt.PyJWK(raw)
            except (KeyError, jwt.PyJWTError):
                continue
        self._keys = keys
        self._keys_at = self._clock()

    def _ask_supabase(self, token: str) -> Caller:
        try:
            user = self._fetch_json(
                f"{self._url}/auth/v1/user",
                {"Authorization": f"Bearer {token}", "apikey": self._anon_key},
            )
        except HTTPError as error:
            raise AuthError(f"Supabase rejected the token ({error.code}).") from error
        except (URLError, TimeoutError, ValueError) as error:
            raise AuthError("Could not check the token.") from error
        user_id = user.get("id")
        if not user_id:
            raise AuthError("Supabase returned no user.")
        return Caller(user_id=str(user_id), is_anonymous=bool(user.get("is_anonymous")))


class RateLimiter:
    """Sliding-window limits per key, kept in this instance's memory.

    Approximate by design: each Cloud Run instance counts on its own, so the
    real ceiling is these limits times the instance cap (--max-instances).
    """

    def __init__(
        self,
        limits: list[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits  # (max requests, window seconds)
        self._window = max(seconds for _, seconds in limits)
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Records a request for [key] unless it would break a limit."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self._window:
                hits.popleft()
            for limit, seconds in self._limits:
                if sum(1 for at in hits if now - at <= seconds) >= limit:
                    return False
            hits.append(now)
            if len(self._hits) > 10000:
                # Forget users with nothing in the window.
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return True
