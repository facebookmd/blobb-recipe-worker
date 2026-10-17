"""A food whose only portions are USDA "RACC" (or a bare 100 g) loses to a
same-named food with a portion people can measure, whatever the recipe unit,
and still matches when it is the only candidate.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import recipe_matcher as matcher


def portion(portion_id, label, grams):
    return {"portion_id": portion_id, "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": 1}


def pork(fdc_id, data_type, portions):
    return {"fdc_id": fdc_id, "source": "usda", "data_type": data_type,
            "display_name": "Ground pork, raw",
            "raw_description": "Ground pork, raw",
            "energy_kcal": 263.0, "is_raw": True, "portions": portions}


RACC_ONLY = pork("2514745", "Foundation", [portion("r-1", "1 RACC", 85.0),
                                           portion("r-2", "100 g", 100.0)])
WITH_OZ = pork("167902", "SR Legacy", [portion("o-1", "1 oz", 28.35)])


@pytest.mark.parametrize("unit", ["oz", "piece"])
def test_a_measurable_portion_beats_racc_only(unit):
    # RACC row first, so list order and the tie-breaks would keep it.
    food, score, _ = matcher._score_list(
        "ground pork", [RACC_ONLY, WITH_OZ], 0.0, False, unit=unit)
    assert food["fdc_id"] == "167902"
    assert score >= matcher.MIN_CONFIDENCE


@pytest.mark.parametrize("unit", ["oz", "piece"])
def test_racc_only_still_matches_alone_at_its_real_score(unit):
    alone, alone_score, _ = matcher._score_list(
        "ground pork", [RACC_ONLY], 0.0, False, unit=unit)
    _, oz_score, _ = matcher._score_list(
        "ground pork", [WITH_OZ], 0.0, False, unit=unit)
    assert alone["fdc_id"] == "2514745"
    assert alone_score == pytest.approx(oz_score)
