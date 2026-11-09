"""Cup and spoon lines that came out as "100 g", the food's basis: the
search took a Foundation row whose only portion is a RACC, and its SR
Legacy row with the cup was found only to lend a density (3 Nov 2026).

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

import parse_recipe
import recipe_matcher as matcher


def portion(idx, label, grams):
    return {"portion_id": f"p{idx}", "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": idx}


def usda(fdc_id, name, portions, kcal, raw=None):
    return {"fdc_id": fdc_id, "source": "usda", "display_name": name,
            "raw_description": raw or name, "energy_kcal": kcal,
            "category": "Vegetables and Vegetable Products", "portions": portions}


BABY_SPINACH = {**usda("1999632", "Spinach, baby", [portion(1, "1 RACC", 85.0)], 20.7),
                "data_type": "Foundation"}
RAW_SPINACH = usda("168462", "Spinach, raw", [portion(1, "1 cup", 30.0)], 23.0)


def test_the_same_food_outside_the_lines_search_is_matched():
    # "baby spinach" finds only the Foundation row; "spinach" finds the SR one.
    pool = {"baby spinach": [BABY_SPINACH], "baby": [], "spinach": [RAW_SPINACH]}
    with mock.patch.object(matcher, "_search_usda_for_ingredient", lambda q: pool.get(q, [])):
        food = matcher._volume_unit_fallback(BABY_SPINACH, [BABY_SPINACH], "cup",
                                             "baby spinach", ["baby", "spinach"])
    assert food["fdc_id"] == RAW_SPINACH["fdc_id"]
    assert food["_same_food_as"] == BABY_SPINACH["fdc_id"]
    assert matcher.pick_best_portion(food, "cup", None, 0.8, "baby spinach")["label"] == "1 cup"


def test_all_types_is_no_word_about_the_food():
    foundation = usda("2515376", "Peanuts, raw", [], 551.0)
    sr = usda("172430", "Peanuts, all types, raw", [], 567.0)
    assert matcher._same_usda_food(foundation, sr)


def test_another_state_is_not_the_same_food():
    canned = usda("2685578", "Whole tomatoes, canned, with liquid, salted", [], 19.1,
                  raw="Tomatoes, whole, canned, solids and liquids, with salt added")
    raw = usda("2709719", "Tomatoes, raw", [], 18.0)
    assert not matcher._same_usda_food(canned, raw)


def test_a_broader_row_naming_its_own_kind_is_not_the_same_food():
    # "white" is a standard word (flour, sugar), but "Bread, white" names
    # a kind of bread: Italian bread keeps its slice (9 Nov 2026).
    italian = usda("174913", "Italian bread", [portion(1, "1 slice", 29.0)], 259.0,
                   raw="Bread, Italian")
    white = usda("2707598", "Bread, white", [portion(1, "1 cup", 40.0)], 266.0)
    assert not matcher._same_usda_food(italian, white)
    # A broader row saying only labelling words still is.
    semolina = usda("2", "Flour, semolina, fine", [], 362.0)
    assert matcher._same_usda_food(semolina, usda("1", "Semolina, enriched", [], 360.0))


def test_rows_each_saying_a_kind_the_other_doesnt_are_different_foods():
    # "whole" and "white" are everyday words, ignored by search ranking but
    # not here: whole wheat flour isn't white all-purpose (9 Nov 2026).
    whole = usda("790085", "Whole wheat flour, unenriched", [], 370.0,
                 raw="Flour, whole wheat, unenriched")
    white = usda("169761", "Wheat flour, white, all-purpose, unenriched", [], 364.0)
    assert not matcher._same_usda_food(whole, white)
    # Only one row adding the everyday kind is the same food.
    foundation = usda("789890", "Flour, wheat, all-purpose, enriched, bleached", [], 366.0)
    sr = usda("168894", "Wheat flour, white, all-purpose, enriched, bleached", [], 364.0)
    assert matcher._same_usda_food(foundation, sr)


# ── Live: each line has a household portion ───────────────────────────────

LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                          reason="needs SUPABASE_ANON_KEY (live Supabase)")


@LIVE
@pytest.mark.parametrize("line,food,label", [
    ("5 cup baby spinach", "Spinach, raw", "1 cup"),
    ("3.5 cup sliced cremini mushrooms", "Brown mushrooms, italian, or crimini, raw", "1 cup sliced"),
    ("3 tbsp semolina flour", "Semolina, enriched", "1 cup"),
    ("3/4 cup crushed peanuts", "Peanuts, raw", "1 cup"),
    ("1 cup whole almonds", "Almonds", "1 cup, whole"),
    ("9 cup cubed Italian bread", "Italian bread", "1 slice"),
    ("3.25 cup canned whole tomatoes", "Ripe red tomatoes, canned, packed in tomato juice", "1 cup"),
])
def test_the_line_has_a_household_portion(line, food, label):
    row = parse_recipe.parse_ingredient_line(line)
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    ingredient = f"{row['size_hint']} {row['ingredient']}".strip()
    found = matcher.match_ingredient(ingredient, rules, unit=row["unit"])[0]
    assert found is not None and found["display_name"] == food
    picked = matcher.pick_best_portion(found, row["unit"], None, float(row["qty"]), ingredient, rules)
    assert picked is not None and picked["label"] == label
