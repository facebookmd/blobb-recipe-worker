"""A slice of kamaboko is 13 g, not the label's 2 oz piece (57 g).

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher

RULES = matcher.load_boosts("boosts.json")
LABEL_PIECE = {"source": "branded", "display_name": "RED KAMABOKO STEAMED FISHCAKE",
               "portions": [{"portion_id": "b1", "label": "2 onz", "gram_weight": 57.0,
                             "gram_col": "", "portion_idx": 1}]}


@pytest.mark.parametrize("ingredient", [
    "kamaboko", "narutomaki", "steamed fish cake", "japanese fish cake",
])
def test_a_slice_is_13_grams(ingredient):
    portion = matcher.pick_best_portion(LABEL_PIECE, "slice", None, 1.0,
                                        ingredient, RULES)
    assert portion["label"] == "1 slice"
    assert portion["gram_weight"] == 13.0


def test_other_units_keep_the_label_serving():
    portion = matcher.pick_best_portion(LABEL_PIECE, "oz", None, 1.0,
                                        "kamaboko", RULES)
    assert portion["gram_weight"] == 57.0
