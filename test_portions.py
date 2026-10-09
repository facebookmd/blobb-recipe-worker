"""A cup measure stays in cups when the food has only spoon portions.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher


def portion(portion_id, label, grams):
    return {"portion_id": portion_id, "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": 1}


TBSP = portion("v-1", "1 tablespoon", 15.0)
VINEGAR = {"portions": [TBSP, portion("v-2", "1 teaspoon", 5.0)]}


def cup_for(food, chosen, recipe_qty, unit):
    """What the matcher swaps in for [recipe_qty] [unit] measured against
    [chosen], as build_output_rows computes the amount (by volume)."""
    spoons = matcher._volume_to_tsp(recipe_qty, unit) / matcher._volume_to_tsp(
        *matcher._portion_label_volume_qty(chosen["label"]))
    return matcher._cup_portion_for_spoon(food, chosen, spoons, unit)


@pytest.mark.parametrize("qty", [0.5, 0.25, 1.0, 2.0])
def test_a_cup_measure_comes_back_in_cups(qty):
    cup = cup_for(VINEGAR, TBSP, qty, "cup")

    assert cup["label"] == "1 cup"
    assert cup["gram_weight"] == pytest.approx(240.0)  # 16 tablespoons
    assert cup["_derived_cup"] is True
    recipe_grams = qty * 16 * TBSP["gram_weight"]
    assert recipe_grams / cup["gram_weight"] == pytest.approx(qty)


def test_cups_plural_counts_too():
    assert cup_for(VINEGAR, TBSP, 0.5, "cups")["label"] == "1 cup"


def test_under_a_quarter_cup_stays_in_spoons():
    # 2 tablespoons: small amounts read better in spoons (SPOON_SWITCH_CUPS).
    assert cup_for(VINEGAR, TBSP, 0.125, "cup") is None


@pytest.mark.parametrize("unit", ["tbsp", "tablespoon", "tsp", "ml", "g", ""])
def test_other_recipe_units_are_left_alone(unit):
    assert matcher._cup_portion_for_spoon(VINEGAR, TBSP, 8.0, unit) is None


def test_a_cup_chosen_already_is_left_alone():
    cup = portion("m-1", "1 cup", 244.0)
    assert matcher._cup_portion_for_spoon({"portions": [cup]}, cup, 0.5, "cup") is None


def test_the_food_s_own_cup_is_used_when_it_has_one():
    own_cup = portion("s-3", "1 cup", 255.0)
    food = {"portions": [TBSP, own_cup]}
    assert cup_for(food, TBSP, 0.5, "cup") is own_cup


def test_a_chunky_cup_is_not_used():
    # "1 cup, chopped" measures pieces; work the cup out from the spoon.
    food = {"portions": [TBSP, portion("x-3", "1 cup, chopped", 150.0)]}
    cup = cup_for(food, TBSP, 0.5, "cup")
    assert cup["_derived_cup"] is True
    assert cup["gram_weight"] == pytest.approx(240.0)


def test_a_teaspoon_portion_scales_by_48():
    tsp = portion("t-1", "1 teaspoon", 5.0)
    cup = cup_for({"portions": [tsp]}, tsp, 0.5, "cup")
    assert cup["gram_weight"] == pytest.approx(240.0)
