"""The ranking rules the recipe matcher shares with the app's food search
(blobb-app): its word lists (search_rules.json) and the cases both must pass
(search_rank_cases.json). The app runs the same cases in
test/search_rules_shared_test.dart.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import recipe_matcher as matcher

HERE = Path(__file__).parent
CASES = json.loads((HERE / "search_rank_cases.json").read_text())
APP = HERE.parent / "blobbapp"


@pytest.mark.parametrize("mine,theirs", [
    ("search_rules.json", "lib/data/search_rules.json"),
    ("search_rank_cases.json", "test/search_rank_cases.json"),
])
def test_matches_the_apps_copy(mine, theirs):
    # The app's copy, when its checkout sits next to this one.
    sibling = APP / theirs
    if not sibling.exists():
        pytest.skip("no blobb-app checkout")
    assert (HERE / mine).read_text() == sibling.read_text(), "copy one over the other"


@pytest.mark.parametrize("token,folded", CASES["tokens"])
def test_plural_folding(token, folded):
    assert matcher._canonical_token(token) == folded


@pytest.mark.parametrize("case", CASES["head_qualifiers"], ids=lambda c: c["query"])
def test_head_qualifiers(case):
    food = {"raw_description": case["description"],
            "display_name": case.get("display_name", case["description"])}
    assert matcher._usda_head_qualifiers(case["query"], food) == case["expect"]


@pytest.mark.parametrize("case", CASES["variant_count"], ids=lambda c: c["query"])
def test_variant_count(case):
    food = {"raw_description": case["description"]}
    assert matcher._usda_variant_count(case["query"], food) == case["expect"]


@pytest.mark.parametrize("case", CASES["modifies"], ids=lambda c: f"{c['query']}|{c['name']}")
def test_a_name_that_only_uses_the_food_to_describe_another(case):
    assert matcher._query_modifies(case["query"], case["name"]) == case["expect"]


def _food(i: int, c: dict) -> dict:
    branded = c.get("branded", False)
    data_type = c.get("data_type", "Branded" if branded else "SR Legacy")
    row = {"id": i + 1, "fdc_id": i + 1,
           "source_set": "branded" if branded else data_type.lower().replace(" ", "_"),
           "data_type": data_type, "description": c["description"],
           "display_name": c.get("display_name", c["description"]),
           "calories_100g": c.get("kcal", 100)}
    # One measurable portion each, so none loses for having none.
    portions = {i + 1: [{"label": "1 cup", "grams": 100.0, "sequence_number": 1}]}
    build = matcher._build_supabase_branded_food if branded else matcher._build_supabase_usda_food
    return build(row, i, portions)


@pytest.mark.parametrize("case", CASES["rank"], ids=lambda c: c["query"])
def test_ranks_the_plain_food_first(case):
    foods = [_food(i, c) for i, c in enumerate(case["candidates"])]
    best = matcher._score_list(matcher.normalise(case["query"]), foods, 0.0, False)[0]
    assert best is not None
    assert best["raw_description"] == case["first"]


# Cooking words are the matcher's alone (search_rules.json "cooking_words"):
# a recipe's food is raw, someone logging quinoa ate it cooked.
@pytest.mark.parametrize("query,description,is_cooked,expect", [
    ("bacon", "Pork, cured, bacon, cooked, baked", False, 1),       # one cooking state
    ("baked potato", "Potatoes, baked, flesh and skin, cooked", False, 0),
    ("green beans", "Green beans, fresh, cooked with oil", False, 1),
    ("rice", "Rice, white, long-grain, regular, enriched, cooked", True, 0),
])
def test_a_recipe_food_is_raw_unless_the_line_says_cooked(query, description, is_cooked, expect):
    food = {"raw_description": description}
    assert matcher._usda_variant_count(query, food, is_cooked) == expect
