"""Ingredients that used to go unmatched (10 Oct 2026): tomato puree, dry
white wine, tomato paste, melted butter.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher
import supabase_food_source as source


def test_accents_fold_to_plain_letters():
    # USDA spells it "Tomato purée"; dropping the é left "pur e".
    assert matcher.normalise("Tomato purée, canned") == "tomato puree  canned"
    assert matcher.normalise("Crème fraîche") == "creme fraiche"


FOOD = {"display_name": "White wine", "fdc_id": "174837"}
NONE = (None, 0.0, "none", None)
# Rules that rewrite nothing in these tests.
RULES = [{"trigger": "unrelated", "boost": "other"}]


@pytest.fixture
def once(monkeypatch):
    """Stand-in for one matching pass: matches only what it is told to."""
    calls = []
    # (ingredient, True) matches with the rules given; (ingredient, False)
    # only on the pass made without any rules.
    matches: dict[tuple[str, bool], tuple] = {}

    def fake(ingredient, boost_rules=None, threshold=0.45, category="",
             unit="", is_cooked=False):
        with_rules = boost_rules != []
        calls.append((ingredient, with_rules))
        return matches.get((ingredient, with_rules), NONE)

    monkeypatch.setattr(matcher, "_match_ingredient_once", fake)
    return matches, calls


def test_a_match_is_returned_as_is(once):
    matches, calls = once
    matches[("white wine", True)] = (FOOD, 3.1, "high", None)
    assert matcher.match_ingredient("white wine", RULES)[0] is FOOD
    assert len(calls) == 1


def test_leading_state_words_are_dropped_when_nothing_matches(once):
    matches, calls = once
    matches[("white wine", True)] = (FOOD, 3.1, "high", None)
    assert matcher.match_ingredient("dry white wine", RULES)[0] is FOOD
    assert [c[0] for c in calls] == ["dry white wine", "white wine"]


def test_a_food_word_is_never_dropped(once):
    _, calls = once
    # "tomato" is not a state word: no retry as "puree".
    assert matcher.match_ingredient("tomato puree", RULES)[0] is None
    assert [c[0] for c in calls] == ["tomato puree"]


def test_the_last_word_is_kept(once):
    _, calls = once
    matcher.match_ingredient("fresh dry", RULES)
    assert [c[0] for c in calls] == ["fresh dry", "dry"]


def test_a_rewrite_that_finds_nothing_falls_back_to_the_recipe_words(once):
    matches, calls = once
    rules = [{"trigger": "tomato puree", "boost": "tomato paste canned"}]
    matches[("tomato puree", False)] = (FOOD, 2.0, "high", None)
    assert matcher.match_ingredient("tomato puree", rules)[0] is FOOD
    assert calls == [("tomato puree", True), ("tomato puree", False)]


def test_no_rewrite_means_no_second_pass_without_rules(once):
    _, calls = once
    matcher.match_ingredient("tomato puree", [{"trigger": "x", "boost": "y"}])
    assert calls == [("tomato puree", True)]


def test_name_search_runs_even_when_full_text_fills_the_limit(monkeypatch):
    # Branded full-text search also matches ingredient lists: "dry white
    # wine" filled every row with salad kits, and the products named that
    # were never fetched.
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test")
    requests = []

    def fake_request(url):
        requests.append(url)
        if "or=(" in url:
            return [{"id": 999, "display_name": "DRY WHITE COOKING WINE"}]
        if "search_vector=fts" in url and "display_name=ilike" not in url:
            return [{"id": i, "display_name": f"SALAD KIT {i}"} for i in range(5)]
        return []

    monkeypatch.setattr(source, "_request_json", fake_request)
    rows = source.search_foods("dry white wine", source_set="branded", limit=5)

    assert any("or=(" in url for url in requests)
    assert 999 in [row["id"] for row in rows]
    assert [row["id"] for row in rows][:5] == [0, 1, 2, 3, 4], (
        "full-text rows keep their place; name matches are added after")


def test_parallel_requests_keep_their_order_and_survive_a_failure(monkeypatch):
    import time

    def fake_request(url):
        if url == "bad":
            raise RuntimeError("Supabase request failed (500) for bad: boom")
        time.sleep(0.05 if url == "slow" else 0)
        return [{"id": url}]

    monkeypatch.setattr(source, "_request_json", fake_request)
    results = source._request_all([("a", "slow"), ("b", "bad"), ("c", "fast")])
    assert results == [[{"id": "slow"}], [], [{"id": "fast"}]]


def test_portion_batches_are_merged_in_order(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test")

    def fake_request(url):
        ids = url.split("food_id=in.(")[1].split(")")[0].split(",")
        return [{"food_id": int(i), "id": int(i)} for i in ids]

    monkeypatch.setattr(source, "_request_json", fake_request)
    grouped = source.load_portions_for_food_ids(list(range(1, 121)))
    assert sorted(grouped) == list(range(1, 121))


def test_responses_are_requested_and_read_gzipped(monkeypatch):
    import gzip
    import json

    monkeypatch.setenv("SUPABASE_ANON_KEY", "test")
    seen = {}

    class Response:
        headers = {"Content-Encoding": "gzip"}

        def read(self):
            return gzip.compress(json.dumps([{"id": 1}]).encode())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        seen["encoding"] = req.get_header("Accept-encoding")
        return Response()

    monkeypatch.setattr(source, "urlopen", fake_urlopen)
    assert source._request_json("https://example/rest/v1/foods") == [{"id": 1}]
    assert seen["encoding"] == "gzip"
