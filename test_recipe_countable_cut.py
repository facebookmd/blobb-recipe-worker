"""A cut named after the food is counted in that cut.

"2 boneless pork loin chop" in a recipe for two came out as 1 oz of pork
loin (56 kcal) per serving. The parser read the trailing "chop" as a prep
step ("onion chop"), so the line was 1 piece, the piece fell back to the
food's first portion, "4 oz", and the count was divided by that 4.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher

# Live values (Supabase, 17 Oct 2026).
PORK_LOIN = matcher._build_supabase_usda_food(
    {"id": 670, "fdc_id": 167818, "source_set": "sr_legacy",
     "description": "Pork, fresh, loin, whole, separable lean and fat, raw",
     "display_name": "Whole pork loin, raw", "calories_100g": 198},
    0, {670: [{"label": "oz", "value": 4.0, "grams": 113.0, "sequence_number": 1},
              {"label": "chop, excluding refuse (yield from 1 raw chop, with refuse, "
                        "weighing 151 g)", "value": 1.0, "grams": 117.0,
               "sequence_number": 2}]})


def row_for(tmp_path, monkeypatch, lines, food):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda *a, **k: (food, 1.0, "high", None))
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(["Test", *lines], name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    [row] = [r for r in matcher.build_output_rows(str(csv), [], 0.0)
             if r.get("_type") == "data"]
    return row


@pytest.mark.parametrize("line, unit, name", [
    ("2 boneless pork loin chop", "chop", "boneless pork loin"),
    ("2 pork chops", "chop", "pork"),
    ("2 bread slice", "slice", "bread"),
])
def test_a_trailing_cut_is_the_unit(line, unit, name):
    parsed = parse_recipe.parse_ingredient_line(line)
    assert (parsed["unit"], parsed["ingredient"]) == (unit, name)


def test_a_trailing_prep_word_is_still_a_hint():
    parsed = parse_recipe.parse_ingredient_line("1 lb pork cube")
    assert (parsed["unit"], parsed["ingredient"], parsed["size_hint"]) == (
        "lb", "pork", "cube")


def test_chops_are_counted_in_chops(tmp_path, monkeypatch):
    row = row_for(tmp_path, monkeypatch, ["2 boneless pork loin chop"], PORK_LOIN)
    assert row["unit_label"].startswith("1 chop")
    assert row["portion_amt"] == pytest.approx(2.0)


def test_a_piece_against_a_weight_portion_is_one_portion(tmp_path, monkeypatch):
    # No count portion to measure a piece: one piece is one 4 oz portion,
    # not a quarter of one.
    food = dict(PORK_LOIN, portions=PORK_LOIN["portions"][:1])
    row = row_for(tmp_path, monkeypatch, ["2 pork loin"], food)
    assert row["unit_label"] == "4 oz"
    assert row["portion_amt"] == pytest.approx(2.0)
