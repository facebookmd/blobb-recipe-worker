"""Offal is not generic meat: "pork blood" was matched to cooked pork through
the generic-meat shortcut (22 Oct 2026), 201 kcal/100 g instead of blood's 77.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

from recipe_layer_stub import best


def _food(fdc_id, name, kcal, raw):
    return {
        "source": "usda", "row": 0, "fdc_id": fdc_id, "display_name": name,
        "raw_description": name, "alt_names": [], "category": "Pork Products",
        "data_type": "SR Legacy", "energy_kcal": kcal, "is_raw": raw,
        "portions": [{"portion_id": f"{fdc_id}-1", "label": "cup",
                      "gram_weight": 237.0, "gram_col": "", "portion_idx": 1}],
    }


BLOOD = _food("9000000001", "Pork blood, raw", 77.0, True)
COOKED_PORK = _food("167855", "Pork, general, lean only, cooked", 201.0, False)


def test_pork_blood_is_not_generic_cooked_pork():
    assert best("pork blood", [COOKED_PORK, BLOOD], "cup") is BLOOD
