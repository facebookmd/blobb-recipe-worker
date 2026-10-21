"""A template's unit_label is the USDA portion's display_label (`medium` for
'medium (4-1/8" long)'), with the count kept in front for the import to
divide out. The matcher's own unit maths keep reading the raw label.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher


@pytest.mark.parametrize("row, label, expected", [
    ({"label": 'medium (4-1/8" long)', "value": 1, "display_label": "medium"},
     '1 medium (4-1/8" long)', "1 medium"),
    ({"label": "1 cup", "display_label": "cup"}, "1 cup", "1 cup"),
    ({"label": "1/2 English muffin", "display_label": "English muffin"},
     "1/2 English muffin", "1/2 English muffin"),
    ({"label": "tbsp", "value": 2, "display_label": "tbsp"}, "2 tbsp", "2 tbsp"),
    ({"label": "chop, excluding refuse (yield from 1 raw chop, with refuse, weighing 113 g)",
      "value": 1, "display_label": "chop"},
     "1 chop, excluding refuse (yield from 1 raw chop, with refuse, weighing 113 g)", "1 chop"),
    ({"label": "Quantity not specified", "display_label": "serving"},
     "Quantity not specified", "serving"),
    # RACC rows have no display_label.
    ({"label": "RACC", "value": 1}, "1 RACC", "1 RACC"),
])
def test_display_label(row, label, expected):
    assert matcher._portion_display_label(row, label) == expected


def test_output_uses_the_display_label_for_the_matched_portion():
    row = {"_type": "data", "unit_label": '1 medium (4-1/8" long)',
           "_unit_display": ('1 medium (4-1/8" long)', "1 medium")}
    assert matcher._with_display_unit(row)["unit_label"] == "1 medium"


def test_a_unit_the_matcher_made_keeps_its_label():
    # A pinch made from the food's tsp portion: unit_label moved on.
    row = {"_type": "data", "unit_label": matcher.PINCH_LABEL,
           "_unit_display": ("1 tsp, ground", "1 tsp, ground")}
    assert matcher._with_display_unit(row)["unit_label"] == matcher.PINCH_LABEL
