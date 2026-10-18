"""Count units pick a whole-item portion, not the food's first one: "1 stalk
green onion" is one medium stalk (15 g), not "1 cup, chopped" (100 g), which
is first in the USDA list.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher


def portion(idx, label, grams):
    return {"portion_id": f"p{idx}", "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": idx}


GREEN_ONION = {"source": "usda", "display_name": "Spring onions or scallions, raw",
               "portions": [portion(1, "1 cup, chopped", 100.0),
                            portion(2, "1 tbsp chopped", 6.0),
                            portion(3, "1 large", 25.0),
                            portion(4, '1 medium (4-1/8" long)', 15.0),
                            portion(5, '1 small (3" long)', 5.0)]}
CELERY = {"source": "usda", "display_name": "Celery, raw",
          "portions": [portion(1, "1 cup chopped", 101.0),
                       portion(2, '1 stalk, large (11"-12" long)', 64.0),
                       portion(3, '1 stalk, medium (7-1/2" - 8" long)', 40.0),
                       portion(4, '1 stalk, small (5" long)', 17.0)]}
SHIITAKE = {"source": "usda", "display_name": "Shiitake mushrooms, raw",
            "portions": [portion(1, "1 piece whole", 19.0)]}
PARSLEY = {"source": "usda", "display_name": "Parsley, fresh",
           "portions": [portion(1, "1 cup chopped", 60.0),
                        portion(2, "10 sprigs", 10.0)]}


def picked(food, unit, ingredient):
    return matcher.pick_best_portion(food, unit, None, 1.0, ingredient, None)["label"]


@pytest.mark.parametrize("food, unit, ingredient, label", [
    (GREEN_ONION, "stalk", "green onion", '1 medium (4-1/8" long)'),
    (GREEN_ONION, "stalks", "green onion", '1 medium (4-1/8" long)'),
    (CELERY, "stalk", "celery", '1 stalk, medium (7-1/2" - 8" long)'),
    (GREEN_ONION, "whole", "green onion", '1 medium (4-1/8" long)'),
    (SHIITAKE, "whole", "shiitake mushroom", "1 piece whole"),
    (PARSLEY, "sprig", "parsley", "10 sprigs"),
])
def test_count_unit_picks_a_whole_item(food, unit, ingredient, label):
    assert picked(food, unit, ingredient) == label


def test_a_named_size_still_wins():
    assert picked(GREEN_ONION, "stalk", "large green onion") == "1 large"


def test_a_sprig_counts_against_the_label_number():
    # "10 sprigs" is ten sprigs, so one sprig is a tenth of that portion.
    assert matcher._portion_label_qty("10 sprigs") == 10.0
