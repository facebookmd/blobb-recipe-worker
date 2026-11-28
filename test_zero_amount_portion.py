"""A portion USDA publishes with amount 0 can't measure anything (28 Nov 2026).

SR's roasted broiler (171450) had "chicken, bone removed", 299 g, at amount
0 until the USDA project's 20261128120000 gave it its 0.5: "1 roasted whole
chicken" read "0 chicken, bone removed" and divided by zero. Rennin mixes'
"cup" (142 g) keeps its 0, as USDA has it.
"""

import recipe_matcher as matcher

ROASTED = {"id": 4302, "fdc_id": 171450, "source_set": "sr_legacy",
           "description": "Chicken, broilers or fryers, meat and skin, cooked, roasted",
           "display_name": "Chicken, with skin, roasted", "calories_100g": 239}


def _row(label, value, grams):
    return {"label": label, "value": value, "amount": value, "grams": grams,
            "display_label": label}


def _labels(portion_rows):
    food = matcher._build_supabase_usda_food(ROASTED, 0, {4302: portion_rows})
    return [p["label"] for p in food["portions"]]


def test_a_zero_amount_portion_is_left_out():
    labels = _labels([_row("oz", 3.0, 85.0), _row("chicken, bone removed", 0.0, 299.0)])
    assert labels == ["3 oz"]


def test_the_fixed_half_chicken_is_kept():
    labels = _labels([_row("oz", 3.0, 85.0), _row("chicken, bone removed", 0.5, 299.0)])
    assert labels == ["3 oz", "0.5 chicken, bone removed"]
    assert matcher._portion_label_qty(labels[1]) == 0.5


def test_numbered_labels_are_not_zero_amount():
    assert not matcher._is_zero_amount_label("0.5 chicken, bone removed")
    assert not matcher._is_zero_amount_label("1 cup")
    assert matcher._is_zero_amount_label("0 cup")
    assert matcher._is_zero_amount_label("0.0 chicken, bone removed")
