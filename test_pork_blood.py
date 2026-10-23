"""Offal is not generic meat: "pork blood" was matched to cooked pork through
the generic-meat shortcut (22 Oct 2026), 201 kcal/100 g instead of blood's 77.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import recipe_matcher as matcher


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


def test_pork_blood_is_not_generic_cooked_pork(monkeypatch):
    def search(query):
        index = matcher.USDAIndex()
        index.add(BLOOD)
        return index

    monkeypatch.setattr(matcher, "_search_usda_for_ingredient", search)
    monkeypatch.setattr(matcher, "_search_branded_for_ingredient",
                        lambda query: matcher.USDAIndex())
    # The shortcut fetches its food by id when the search didn't return it.
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id",
                        lambda fdc_id: COOKED_PORK if fdc_id == "167855" else None)

    food, _, _, _ = matcher._match_ingredient_once(
        "pork blood", [], 0.45, "filipino", "cup", False)
    assert food is not None and food["fdc_id"] == "9000000001"
