"""A failed Supabase request in a batch run stops the run (21 Oct 2026): taken
as no rows, a lost portion lookup wrote Yakisoba's oyster sauce as 1/4 of
100 g. The Convert recipe server keeps warning and going on.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import sys
from urllib.error import URLError

import pytest

import recipe_matcher as matcher
import supabase_food_source as source


@pytest.fixture(autouse=True)
def lenient_afterwards():
    yield
    source.fail_on_request_errors(False)


def failing(path):
    raise RuntimeError(f"Supabase request failed for {path}: nodename nor servname")


def test_the_server_counts_a_failed_request_as_no_rows(monkeypatch, capsys):
    monkeypatch.setattr(source, "_request_json", failing)
    assert source._request_all([("portion lookup", "u1"), ("portion lookup", "u2")]) == [[], []]
    assert "[!] Supabase portion lookup failed" in capsys.readouterr().err


def test_a_batch_run_raises_on_a_failed_request(monkeypatch):
    source.fail_on_request_errors()
    monkeypatch.setattr(source, "_request_json", failing)
    with pytest.raises(source.SupabaseLookupError, match="portion lookup failed"):
        source._request_all([("portion lookup", "u1"), ("portion lookup", "u2")])


def test_a_batch_run_raises_on_a_failed_fdc_lookup(monkeypatch):
    source.fail_on_request_errors()
    monkeypatch.setattr(source, "is_configured", lambda: True)
    monkeypatch.setattr(source, "_request_json", failing)
    with pytest.raises(source.SupabaseLookupError, match="FDC ID 2707150"):
        source.fetch_food_by_fdc_id(2707150)


class _Response:
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'[{"id": 1}]'


def test_a_dropped_connection_is_tried_once_more(monkeypatch):
    calls = []

    def flaky(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise URLError("nodename nor servname provided")
        return _Response()

    monkeypatch.setattr(source, "urlopen", flaky)
    monkeypatch.setattr(source.time, "sleep", lambda s: None)
    monkeypatch.setattr(source, "_supabase_key", lambda: "key")
    assert source._request_json("https://example.supabase.co/rest/v1/foods") == [{"id": 1}]
    assert len(calls) == 2


def test_the_batch_stops_without_writing_output(monkeypatch, tmp_path, capsys):
    def lost_lookup(*args, **kwargs):
        assert source._fail_on_request_errors
        raise source.SupabaseLookupError("Supabase portion lookup failed: 500")

    output = tmp_path / "templates_output.xlsx"
    monkeypatch.setattr(matcher, "supabase_is_configured", lambda: True)
    monkeypatch.setattr(matcher, "build_output_rows", lost_lookup)
    monkeypatch.setattr(sys, "argv", [
        "recipe_matcher.py", "--forceall",
        "--recipes", str(tmp_path / "recipes.csv"),
        "--output", str(output),
    ])
    with pytest.raises(SystemExit) as stop:
        matcher.main()
    assert stop.value.code == 1
    assert not output.exists()
    assert not output.with_suffix(".csv").exists()
    assert "output files were not changed" in capsys.readouterr().err


# ── Retries under load (28 Oct 2026) ────────────────────────────────────────
# One retry after 1 s still lost ~20 searches a full run to statement
# timeouts, so a run's matches changed from run to run.

def _http_error(code, body):
    import gzip
    import io
    from urllib.error import HTTPError
    return HTTPError("https://example.supabase.co/rest/v1/foods", code, "error", {},
                     io.BytesIO(gzip.compress(body)))


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(source.time, "sleep", lambda s: None)
    monkeypatch.setattr(source, "_supabase_key", lambda: "key")


def test_a_gzipped_statement_timeout_is_read_and_retried(monkeypatch, no_wait):
    calls = []

    def busy(req, timeout):
        calls.append(req)
        if len(calls) < 4:
            raise _http_error(500, b'{"code":"57014","message":"canceling statement due to statement timeout"}')
        return _Response()

    monkeypatch.setattr(source, "urlopen", busy)
    assert source._request_json("https://example.supabase.co/rest/v1/foods") == [{"id": 1}]
    assert len(calls) == 4


def test_a_lasting_error_gives_up_with_its_reason(monkeypatch, no_wait):
    calls = []

    def down(req, timeout):
        calls.append(req)
        raise _http_error(500, b'{"code":"57014","message":"canceling statement due to statement timeout"}')

    monkeypatch.setattr(source, "urlopen", down)
    with pytest.raises(RuntimeError, match="statement timeout"):
        source._request_json("https://example.supabase.co/rest/v1/foods")
    assert len(calls) == len(source._RETRY_DELAYS) + 1


def test_a_timed_out_read_is_retried(monkeypatch, no_wait):
    calls = []

    def slow(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return _Response()

    monkeypatch.setattr(source, "urlopen", slow)
    assert source._request_json("https://example.supabase.co/rest/v1/foods") == [{"id": 1}]
    assert len(calls) == 2


def test_a_bad_request_is_not_retried(monkeypatch, no_wait):
    calls = []

    def bad(req, timeout):
        calls.append(req)
        raise _http_error(400, b'{"code":"PGRST100","message":"failed to parse"}')

    monkeypatch.setattr(source, "urlopen", bad)
    with pytest.raises(RuntimeError, match="failed to parse"):
        source._request_json("https://example.supabase.co/rest/v1/foods")
    assert len(calls) == 1
