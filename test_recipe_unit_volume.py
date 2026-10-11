"""A volume line stays in the recipe's own unit when the food lists another.

USDA's tap water has fl oz, "serving 8 fl oz" and liter portions but no cup,
so "1 cup water" came out as 8 fl oz and "4 cup water" as 0.95 liter, and a
template reopened as "8 fl oz water". The cup is worked out from the plain
volume portion, as the app derives its own units.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher

# Live values (Supabase, 11 Oct 2026).
WATER = matcher._build_supabase_usda_food(
    {"id": 10, "fdc_id": 173647, "source_set": "sr_legacy",
     "description": "Water, tap, drinking", "display_name": "Tap water, drinking",
     "calories_100g": 0},
    0, {10: [{"label": "fl oz", "grams": 29.6, "sequence_number": 1},
             {"label": "serving 8 fl oz", "grams": 237.0, "sequence_number": 2},
             {"label": "liter", "grams": 1000.0, "sequence_number": 3}]})
SOY_SAUCE = matcher._build_supabase_usda_food(
    {"id": 11, "fdc_id": 174277, "source_set": "sr_legacy",
     "description": "Soy sauce", "display_name": "Soy sauce", "calories_100g": 53},
    0, {11: [{"label": "tbsp", "grams": 16.0, "sequence_number": 1}]})
ONION = matcher._build_supabase_usda_food(
    {"id": 12, "fdc_id": 170000, "source_set": "sr_legacy",
     "description": "Onions, raw", "display_name": "Onion", "calories_100g": 40},
    0, {12: [{"label": "cup, chopped", "grams": 160.0, "sequence_number": 1},
             {"label": "medium", "grams": 110.0, "sequence_number": 2}]})


def row_for(tmp_path, monkeypatch, line, food):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda *a, **k: (food, 1.0, "high", None))
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(["Test", line], name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    [row] = [r for r in matcher.build_output_rows(str(csv), [], 0.0)
             if r.get("_type") == "data"]
    return row


@pytest.mark.parametrize("line, amount, label, grams", [
    ("1 cup water", 1, "1 cup", 236.8),
    ("4 cup water", 4, "1 cup", 236.8),
    ("2 tbsp water", 2, "1 tbsp", 14.8),
    ("250 ml water", 250, "1 ml", 1.0),
])
def test_water_stays_in_the_recipe_unit(tmp_path, monkeypatch, line, amount, label, grams):
    row = row_for(tmp_path, monkeypatch, line, WATER)
    assert row["portion_amt"] == pytest.approx(amount, rel=0.01)
    assert row["unit_label"] == label
    assert row["unit_grams"] == pytest.approx(grams, abs=0.1)


def test_a_sliver_of_a_cup_still_reads_in_spoons(tmp_path, monkeypatch):
    row = row_for(tmp_path, monkeypatch, "1/8 cup soy sauce", SOY_SAUCE)
    assert (row["unit_label"], row["portion_amt"]) == ("tbsp", pytest.approx(2))


def test_a_chopped_cup_is_not_a_volume_basis():
    medium = next(p for p in ONION["portions"] if p["label"] == "medium")
    assert matcher._recipe_unit_volume_portion(ONION, medium, "tbsp") is None


@pytest.mark.parametrize("label, plain", [
    ("fl oz", True), ("1 cup", True), ("2 tbsp", True), ("1 fl oz", True),
    ("cup, chopped", False), ("serving 8 fl oz", False), ("liter", False),
])
def test_plain_volume_labels(label, plain):
    assert matcher._is_plain_volume_label(label) is plain
