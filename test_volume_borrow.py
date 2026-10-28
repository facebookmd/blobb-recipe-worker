"""A cup or spoon line on a food with no volume portion: the volume comes
from a USDA row headed by the same food, and a line that still can't be
measured is an estimate at 1 g/ml, never that many whole items. Bouillon
cubes are counted in cubes.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

from unittest import mock

import pytest

import parse_recipe
import recipe_matcher as matcher


def portion(idx, label, grams):
    return {"portion_id": f"p{idx}", "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": idx}


def usda(fdc_id, name, portions, kcal=80.0):
    return {"fdc_id": fdc_id, "source": "usda", "display_name": name,
            "raw_description": name, "energy_kcal": kcal, "category": "Vegetables",
            "portions": portions}


POTATOES = usda("170026", "Potatoes, flesh and skin, raw",
                [portion(1, "0.5 cup, diced", 75.0), portion(2, "1 medium", 213.0)])
CHOW_MEIN = usda("168919", "Noodles, chow mein", [portion(1, "1 cup", 56.0)], 527.0)
NOODLES = usda("169733", "Noodles, egg, dry", [portion(1, "1 cup", 38.0)], 384.0)


def borrow(name, line, pool):
    food = {"fdc_id": "B_1", "source": "branded", "display_name": name,
            "raw_description": name, "energy_kcal": 70.0}
    with mock.patch.object(matcher, "_search_usda_for_ingredient", lambda q: pool):
        return matcher._density_from_head_food(food, "cup", line)


def test_a_branded_variety_borrows_its_head_foods_cup():
    row, cup = borrow("YUKON GOLD POTATOES", "yukon gold potato", [POTATOES])
    assert row is POTATOES and cup["gram_weight"] == 75.0


def test_a_food_far_off_in_calories_borrows_nothing():
    # Konjac noodles (70 kcal here) aren't dry egg noodles (384).
    assert borrow("ORGANIC KONJAC NOODLES, LINGUINE", "konjac", [CHOW_MEIN, NOODLES]) == (None, None)


def pasta(fid, name, label, grams):
    return {**usda(fid, name, [portion(1, label, grams)], 371.0), "category": "Cereal Grains and Pasta"}


SHELLS = pasta("1", "Pasta, dry, enriched", "1 cup small shells", 64.0)


def borrow_pasta(pool):
    food = {"fdc_id": "B_1", "source": "branded", "display_name": "ACINI DI PEPE PASTA",
            "raw_description": "ACINI DI PEPE PASTA", "energy_kcal": 371.0}
    with mock.patch.object(matcher, "_search_usda_for_ingredient", lambda q: pool):
        return matcher._density_from_head_food(food, "cup", "uncooked acini di pepe")


def test_a_food_measured_by_its_shape_borrows_nothing():
    # Dry pasta's cups by shape differ 1.9x (64 g shells, 123 g elbows).
    elbows = pasta("2", "Pasta, dry, unenriched", "1 cup elbow shaped", 123.0)
    assert borrow_pasta([SHELLS, elbows]) == (None, None)


def test_rows_that_agree_on_the_density_lend_their_cup():
    # The same pool within HEAD_BORROW_SPREAD: the spread is what said no.
    close = pasta("2", "Pasta, dry, unenriched", "1 cup elbow shaped", 70.0)
    row, cup = borrow_pasta([SHELLS, close])
    assert row is SHELLS and cup["gram_weight"] == 64.0


def test_a_spoon_against_a_count_is_1_g_per_ml_not_one_item():
    amount, estimated = matcher._mismatch_amount(1.0, "tsp", portion(1, "1 whole", 180.0))
    assert estimated and amount == pytest.approx(matcher._volume_to_ml(1.0, "tsp") / 180.0)


@pytest.mark.parametrize("line, unit, name", [
    ("1 beef bouillon cube", "cube", "beef bouillon cube"),
    ("2 cubes chicken bouillon", "cube", "chicken bouillon"),
])
def test_bouillon_is_counted_in_cubes(line, unit, name):
    parsed = parse_recipe.parse_ingredient_line(line)
    assert (parsed["unit"], parsed["ingredient"]) == (unit, name)


def test_a_cube_line_picks_the_cube_portion():
    cubes = usda("171563", "Soup, chicken broth cubes, dry",
                 [portion(1, "1 tsp", 2.0), portion(2, "1 cube", 4.8)], 198.0)
    assert matcher.pick_best_portion(cubes, "cube", None, 1.0,
                                     "chicken bouillon cube")["label"] == "1 cube"


# ── A volume line keeps the food's own serving ────────────────────────────

GREEN_OLIVES = usda("169096", "Olives, pickled, canned or bottled, green",
                    [portion(1, "1 olive", 2.7)], 145.0)


def test_a_borrowed_cup_is_a_density_not_a_portion():
    # Arianna, 27 Oct 2026: never a volume the food doesn't have.
    # Not the same food (Manzanilla), so only its density is used.
    relative = usda("2710090", "Olives, green, Manzanilla", [portion(1, "1 cup", 134.4)], 150.0)
    food = matcher._volume_unit_fallback(GREEN_OLIVES, [GREEN_OLIVES, relative], "cup",
                                         "green olives", ["green", "olives"])
    assert food["fdc_id"] == GREEN_OLIVES["fdc_id"]
    assert food["portions"] == GREEN_OLIVES["portions"]
    assert food["_g_per_ml"] == pytest.approx(134.4 / matcher._volume_to_ml(1.0, "cup"))
    assert matcher.pick_best_portion(food, "cup", None, 0.5, "green olives")["label"] == "1 olive"
    # Half a cup of olives, counted in olives.
    amount, _ = matcher._mismatch_amount(0.5, "cup", food["portions"][0], food["_g_per_ml"])
    assert amount == pytest.approx(0.5 * 134.4 / 2.7, rel=0.01)


@pytest.mark.parametrize("labels, picked", [
    ([("1 oz", 28.35), ("1 serving", 148.0)], "1 serving"),     # a serving before a weight
    ([("1 container", 108.0), ("1 bar", 40.0)], "1 bar"),       # a package last
    ([("1 RACC", 85.0), ("1 oz", 28.35)], "1 oz"),              # never a RACC
    ([("100 g", 100.0)], None),                                 # nothing: grams
])
def test_the_own_serving_order(labels, picked):
    food = usda("1", "Food", [portion(i, l, g) for i, (l, g) in enumerate(labels, 1)])
    serving = matcher._own_serving_for_volume(food)
    assert (serving and serving["label"]) == picked


def test_oza_is_a_fluid_ounce():
    assert matcher._portion_label_unit("8 OZA") == "fl oz"


# ── The same food in another USDA dataset, with a cup ─────────────────────

FOUNDATION_FLOUR = {**usda("789890", "Flour, wheat, all-purpose, enriched, bleached",
                           [portion(1, "1 RACC", 30.0)], 366.0), "data_type": "Foundation"}
SR_FLOUR = usda("169761", "Wheat flour, white, all-purpose, enriched, bleached",
                [portion(1, "1 cup", 125.0)], 364.0)
PICKLED = usda("169961", "Beans, snap, green, pickled", [portion(1, "1 cup", 135.0)], 30.0)
RAW_BEANS = usda("169961", "Beans, snap, green, raw", [portion(1, "1 RACC", 85.0)], 31.0)


def test_the_same_food_with_a_cup_is_matched():
    food = matcher._volume_unit_fallback(FOUNDATION_FLOUR, [FOUNDATION_FLOUR, SR_FLOUR], "cup",
                                         "all-purpose flour", ["all", "purpose", "flour"])
    assert food["fdc_id"] == SR_FLOUR["fdc_id"]
    assert food["_same_food_as"] == FOUNDATION_FLOUR["fdc_id"]


@pytest.mark.parametrize("food, cand", [
    (RAW_BEANS, PICKLED),                                                   # another form
    (FOUNDATION_FLOUR, {**SR_FLOUR, "energy_kcal": 250.0}),                # other calories
    (FOUNDATION_FLOUR, {**SR_FLOUR, "source": "branded"}),                 # not USDA
])
def test_not_the_same_food(food, cand):
    assert not matcher._same_usda_food(food, cand)


def test_a_group_label_is_not_a_word_about_the_food():
    almonds = usda("2346393", "Almonds, whole, raw", [], 584.0)
    almonds["raw_description"] = "Nuts, almonds, whole, raw"
    sr = usda("170567", "Almonds, raw", [], 579.0)
    sr["raw_description"] = "Nuts, almonds"
    assert matcher._same_usda_food(almonds, sr)
