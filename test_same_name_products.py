"""Several branded products with the same name (22 Oct 2026).

Twelve products are named "LINGUINE": dry pastas labelled per 2 oz (56 g,
about 357 kcal/100 g), fresh deli pastas per 1 1/4 cup (85 g, 282-306) and a
dinner kit. The first one fetched used to win. Now: the label serving in the
recipe's kind of unit, then the most common serving, then the median calories.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import recipe_matcher as matcher


def linguine(fdc_id, kcal, serving_text, grams):
    return {"source": "branded", "fdc_id": f"B_{fdc_id}", "display_name": "LINGUINE",
            "raw_description": "LINGUINE", "alt_names": [], "energy_kcal": kcal,
            "serving_text": serving_text, "serving_grams": grams,
            "portions": [{"portion_id": f"B_{fdc_id}-1", "label": "1 serving",
                          "gram_weight": grams, "gram_col": "", "portion_idx": 1}]}


FRESH = linguine(1, 282.0, "1 1/4 cup", 85.0)
FRESH_2 = linguine(2, 306.0, "1 1/4 cup", 85.0)
DRY_LOW = linguine(3, 339.0, "2 ONZ", 56.0)
DRY = linguine(4, 357.0, "2 oz", 56.0)
DRY_HIGH = linguine(5, 375.0, "2 ONZ", 56.0)
KIT = linguine(6, 433.0, "3.17 ONZ", 90.0)
ALL = [FRESH, FRESH_2, DRY_LOW, DRY, DRY_HIGH, KIT]


def test_a_weight_line_takes_the_typical_dry_pasta():
    assert matcher._typical_branded(ALL, "oz") is DRY


def test_a_cup_line_takes_a_product_labelled_in_cups():
    assert matcher._typical_branded(ALL, "cup") in (FRESH, FRESH_2)


def test_with_no_label_in_that_kind_of_unit_all_of_them_count():
    # Counts: no label is a count, so the most common serving (56 g) wins.
    assert matcher._typical_branded(ALL, "") is DRY
