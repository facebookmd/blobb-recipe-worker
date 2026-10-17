"""A portion label's amount: "1/8 cup" is an eighth of a cup, so 1/4 cup of
panko against it is 2 portions, not a quarter of one. "bunch" is a count unit.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher


@pytest.mark.parametrize("label, qty", [
    ("1/8 cup", 0.125),
    ("1/3 cup", 1 / 3),
    ("1 1/2 cup", 1.5),
    ("0.5 cup", 0.5),
    ("1 cup", 1.0),
    ("2 tbsp", 2.0),
    ("1 10 Wrappers", 10.0),
    ("bunch", 1.0),
])
def test_label_quantity(label, qty):
    assert matcher._portion_label_qty(label) == pytest.approx(qty)


def test_a_fraction_cup_label_scales_by_volume():
    serving_qty, serving_unit = matcher._portion_label_volume_qty("1/8 cup")
    recipe_ml = matcher._volume_to_ml(0.25, "cup")
    serving_ml = matcher._volume_to_ml(serving_qty, serving_unit)

    assert recipe_ml / serving_ml == pytest.approx(2.0)


def test_bunch_is_a_count_unit():
    assert "bunch" in matcher.PORTION_UNIT_KEYWORDS


RULES = [
    {"trigger": "curry roux", "portion_unit": "block",
     "portion_gram_weight": 20.0, "portion_label": "1 block"},
    {"trigger": "nori", "portion_gram_weight": 2.6, "portion_label": "1 sheet"},
]


def test_a_unit_rule_is_found_when_only_unit_rules_count():
    found = matcher.get_portion_override(
        "boxed japanese curry roux", RULES, "block", unit_rules_only=True)

    assert found["label"] == "1 block"
    assert found["gram_weight"] == 20.0


def test_a_rule_without_a_unit_is_skipped_when_only_unit_rules_count():
    assert matcher.get_portion_override(
        "nori", RULES, "sheet", unit_rules_only=True) is None
    assert matcher.get_portion_override("nori", RULES, "sheet")["label"] == "1 sheet"
