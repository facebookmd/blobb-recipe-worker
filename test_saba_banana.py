"""A saba is USDA's extra-small banana (81 g), not a whole plantain (180 g
and up), 3 Nov 2026: saba weighs about 70-75 g, and 81 g is the closest
whole-fruit portion USDA has.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import recipe_matcher as matcher

HERE = os.path.dirname(__file__)


def test_a_saba_banana_is_an_extra_small_banana():
    rules = matcher.load_boosts(os.path.join(HERE, "boosts.json"))
    pin = [r for r in rules if r.get("trigger") == "saba banana" and r.get("fdc_id")]
    portion = [r for r in rules if r.get("trigger") == "saba banana" and r.get("portion_gram_weight")]
    assert [r["fdc_id"] for r in pin] == ["173944"]          # Bananas, raw
    assert [(r["portion_unit"], r["portion_gram_weight"]) for r in portion] == [("piece", 81.0)]
