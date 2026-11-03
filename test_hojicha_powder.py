"""Hojicha powder stands in with Publix organic matcha: 1 tsp is 2 g, 5 kcal.

No USDA or branded row has hojicha powder. The APAX matcha label (400 kcal
per 100 g, 3 g a teaspoon) reads high next to MEXT's tea leaf (229-237).

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe
import recipe_matcher as matcher

RULES = matcher.load_boosts("boosts.json")


def test_hojicha_is_pinned_to_publix_matcha():
    assert matcher.apply_boosts("hojicha powder", RULES)[2] == "B_2398187"


def test_matcha_keeps_its_own_match():
    assert matcher.apply_boosts("matcha powder", RULES)[2] != "B_2398187"


@pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                    reason="needs SUPABASE_ANON_KEY (live Supabase)")
def test_live_a_teaspoon_is_2_grams(tmp_path):
    meta, ings = parse_recipe.parse_single_block(
        ["Test", "", "Ingredients", "1 tsp hojicha powder"],
        name_hint="recipe", category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    rows = matcher.build_output_rows(str(csv), RULES, 0.0)
    [row] = [r for r in rows if r.get("_type") == "data"]
    assert row["food_id"] == "B_2398187"
    assert row["portion_description"] == "1 tsp (2.0 g)"
    assert row["cal_tot"] == pytest.approx(5.0)
