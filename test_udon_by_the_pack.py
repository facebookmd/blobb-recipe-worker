"""Udon is listed by the pack, as its sources do, not in cooked cups.

"3 cup cooked udon noodles" matched USDA's generic "Noodles, cooked"
(137 kcal/100 g), a third more than boiled udon. The recipe says
"2 pack frozen udon noodles", pinned to Wegmans Asian Classics frozen
udon (B_2074076: 124 kcal/100 g, 1 pouch = 250 g).

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe
import recipe_matcher as matcher

# Live values (Supabase, 21 Oct 2026).
WEGMANS_UDON = matcher._build_supabase_branded_food(
    {"id": 1, "fdc_id": 2074076, "source_set": "branded",
     "description": "ASIAN CLASSICS UDON NOODLES", "display_name": "ASIAN CLASSICS UDON NOODLES",
     "calories_100g": 124, "serving_size": 250.0, "serving_size_unit": "g",
     "household_serving_full_text": "1 POUCH"},
    0, {})


def rows_for(tmp_path, monkeypatch, food, line, servings):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda *a, **k: (food, 1.0, "high", None))
    meta, ings = parse_recipe.parse_single_block(
        ["Test", f"Servings: {servings}", "", "Ingredients", line],
        name_hint="recipe", category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    return [r for r in matcher.build_output_rows(str(csv), [], 0.0)
            if r.get("_type") == "data"]


def test_one_pack_per_serving_is_one_pouch(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, WEGMANS_UDON, "2 pack frozen udon noodles", 2)
    assert row["unit_label"] == "1 pouch"
    assert row["portion_amt"] == pytest.approx(1.0)
    assert row["cal_tot"] == pytest.approx(310.0)
    assert not row["estimated"]


def test_udon_is_pinned_and_cooked_udon_is_not():
    rules = matcher.load_boosts("boosts.json")
    pins = {r.get("trigger"): r.get("fdc_id") for r in rules if r.get("trigger")}
    # parse_recipe drops "frozen", so the line reads "udon noodles".
    assert pins["udon noodles"] == "B_2074076"
    assert "cooked udon noodles" not in pins
    assert pins["cooked ramen noodles"] == "2708352"


@pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                    reason="needs SUPABASE_ANON_KEY (live Supabase)")
def test_live_frozen_udon(tmp_path):
    meta, ings = parse_recipe.parse_single_block(
        ["Test", "Servings: 2", "", "Ingredients", "2 pack frozen udon noodles"],
        name_hint="recipe", category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    rows = matcher.build_output_rows(str(csv), matcher.load_boosts("boosts.json"), 0.0)
    [row] = [r for r in rows if r.get("_type") == "data"]
    assert row["food_id"] == "B_2074076"
    assert row["unit_label"] == "1 pouch"
    assert row["portion_amt"] == pytest.approx(1.0)
