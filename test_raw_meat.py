"""Meat bought by weight is raw: a raw row before a cooked one, and a cooked
row is measured by USDA's own yield where it has one. A branded product is
as sold (27 Oct 2026).

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe as parser
import recipe_matcher as matcher
from recipe_layer_stub import best


def portion(idx, label, grams):
    return {"portion_id": f"p{idx}", "label": label, "gram_weight": grams,
            "gram_col": "", "portion_idx": idx}


def usda(fdc_id, name, portions=(), kcal=250.0, raw=False, data_type="SR Legacy"):
    return {"fdc_id": fdc_id, "source": "usda", "display_name": name, "raw_description": name,
            "energy_kcal": kcal, "is_raw": raw, "data_type": data_type,
            "portions": list(portions)}


OXTAIL = usda("2705843", "Beef, oxtails", [portion(1, "1 tail", 240.0),
                                          portion(2, "1 oz yields", 16.0)],
              257.0, data_type="Survey (FNDDS)")
HAM_HOCKS = usda("2705900", "Pork, ham hocks", [portion(1, "1 ham hock", 85.0)],
                 268.0, data_type="Survey (FNDDS)")
BROILED = usda("169189", "Pork, shoulder, petite tender, boneless, separable lean and fat, cooked, broiled")
RAW_BUTT = usda("167849", "Pork, fresh, shoulder, (Boston butt), blade (steaks), separable lean and fat, raw",
                raw=True, kcal=186.0)
# Flagged raw on purpose: the yield goes by the row's cooking words.
BRAISED_BUTT = usda("167850", "Pork, fresh, shoulder, (Boston butt), blade (steaks), separable lean and fat, "
                    "cooked, braised", raw=True, kcal=267.0)
TOCINO = {**usda("B_2068779", "PORK TOCINO", kcal=165.0), "source": "branded"}


@pytest.mark.parametrize("food, kw, expected", [
    (OXTAIL, "beef", 16.0 / 28.349523125),   # USDA's own: bone and cooking loss
    (HAM_HOCKS, "pork", 0.73),               # FNDDS is as eaten: the generic yield
    (BROILED, "pork", 0.73),
    (BRAISED_BUTT, "pork", 0.73),            # cooked by its words, though "fresh"
    (RAW_BUTT, "pork", None),                # raw: no yield
    (TOCINO, "pork", None),                  # branded: as sold
])
def test_the_cooked_meat_yield(food, kw, expected):
    got = matcher._cooked_meat_yield(food, kw)
    assert got == (pytest.approx(expected) if expected else None)


@pytest.mark.parametrize("line, unit, raw", [
    ("pork shoulder", "lb", True), ("2 lb oxtail", "lb", True),
    ("pork shoulder", "cup", False), ("cooked chicken", "oz", False),
    ("carrot", "lb", False),
])
def test_a_raw_meat_weight_line(line, unit, raw):
    cooked = "cooked" in line
    assert matcher._is_raw_meat_weight_line(line, unit, cooked) is raw


def test_meat_by_weight_prefers_the_raw_row():
    # Same tier: the broiled row came first in layer 1's order.
    broiled = {**BROILED, "display_name": "Pork shoulder, broiled"}
    raw = {**RAW_BUTT, "display_name": "Pork shoulder, raw"}
    assert best("pork shoulder", [broiled, raw], "lb") is raw


# ── Shrimp by weight: meat only, by how the line says it's bought ─────────

SHRIMP = usda("175179", "Crustaceans, shrimp, raw", [portion(1, "3 oz", 85.0)], 85.0, raw=True)


@pytest.mark.parametrize("line, share", [
    ("1 lb head-on shrimp", 0.57 * 0.81),   # USDA AH-102: heads 43%, then shell
    ("1 lb shell-on shrimp", 0.81),
    ("1 lb shrimp, heads on", 0.57 * 0.81),
    ("1 lb unpeeled shrimp", 0.81),
    ("1 lb shrimp in the shell", 0.81),
    ("1 lb shrimp", None),                  # plain shrimp is peeled
    ("16 large shrimp", None),              # a count: USDA's "1 large" is meat
])
def test_shrimp_weighed_as_bought(line, share):
    parsed = parser.parse_ingredient_line(line)
    got = matcher._edible_share(SHRIMP, parsed["as_bought"])
    assert (got and got[0]) == (pytest.approx(share) if share else None)


@pytest.mark.parametrize("line, share", [
    ("1.5 lb milkfish", 0.60),              # whole by default
    ("2 lb boneless milkfish", None),
    ("1 lb milkfish belly", None),
])
def test_milkfish_by_weight_is_the_whole_fish(line, share):
    milkfish = usda("173675", "Fish, milkfish, raw", [portion(1, "3 oz", 85.0)], 148.0, raw=True)
    parsed = parser.parse_ingredient_line(line)
    got = matcher._edible_share(milkfish, parsed["as_bought"])
    assert (got and got[0]) == (pytest.approx(share) if share else None)


def test_pork_hock_takes_the_fresh_shank_half_s_share():
    # The alias is the fresh leg's shank half (SR 10016, 28% refuse); the
    # cured FNDDS ham hock has no SR refuse, so no share (28 Oct 2026).
    parsed = parser.parse_ingredient_line("3 lb pork hock")
    assert parsed["as_bought"] == "bone-in"
    shank = usda("168226", "Pork, fresh, leg (ham), shank half, separable lean and fat, raw",
                 kcal=193.0, raw=True)
    assert matcher._edible_share(shank, parsed["as_bought"])[0] == pytest.approx(0.72)
    assert matcher._edible_share(HAM_HOCKS, parsed["as_bought"]) is None


@pytest.mark.parametrize("line, expected", [
    ("pork belly", "pork"),
    ("beefsteak tomato", None),   # a word, not part of one
    ("hot dog", None),
])
def test_the_meat_keyword_is_a_word(line, expected):
    assert matcher._meat_keyword(line) == expected


# ── Pork shoulder by weight (28 Oct 2026) ───────────────────────────────────
# The alias is cooked braised Boston butt, for someone logging what they ate;
# a recipe's raw weight takes the pork yield, near the raw row (186 kcal).

@pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                    reason="needs SUPABASE_ANON_KEY (live Supabase)")
@pytest.mark.parametrize("line, unit", [("boneless pork shoulder", "lb"), ("pork shoulder", "oz")])
def test_live_pork_shoulder_by_weight_lands_near_raw(line, unit, monkeypatch):
    import food_name_search
    aliases = dict(food_name_search._food_aliases())
    rows = food_name_search.source._request_all(
        [("braised butt", food_name_search._rest("foods?fdc_id=eq.167850&select=id"))])[0]
    aliases[food_name_search.alias_key("pork shoulder")] = int(rows[0]["id"])
    aliases[food_name_search.alias_key("boneless pork shoulder")] = int(rows[0]["id"])
    monkeypatch.setattr(food_name_search, "_ALIASES", aliases)
    food = matcher.match_ingredient(line, [], 0.45, unit=unit)[0]
    assert "braised" in food["raw_description"].lower()
    assert food["_yield_factor"] == pytest.approx(0.73)
    assert food["energy_kcal"] * food["_yield_factor"] == pytest.approx(186.0, rel=0.06)


@pytest.mark.parametrize("description, category, raw", [
    # "fresh" names the pork, not its state (28 Oct 2026).
    ("Pork, fresh, shoulder, (Boston butt), blade (steaks), separable lean and fat, cooked, braised",
     "Pork Products", False),
    ("Pork, fresh, shoulder, (Boston butt), blade (steaks), separable lean and fat, raw",
     "Pork Products", True),
    ("Peppers, sweet, red, fresh", "Vegetables", True),
    ("Broccoli, cooked, boiled", "Vegetables", False),
    # The row's name, not its category: raw dough among "Baked Products".
    ("Cookies, chocolate chip, refrigerated dough, unprepared", "Baked Products", True),
])
def test_a_row_named_cooked_is_not_raw(description, category, raw):
    food = matcher._build_supabase_usda_food(
        {"id": 1, "fdc_id": 1, "source_set": "sr_legacy", "description": description,
         "display_name": description, "category": category, "calories_100g": 100}, 0, {})
    assert food["is_raw"] is raw


# ── Skin-on lines outside chicken (13 Nov 2026) ─────────────────────────────
# "skin-on pork belly" went without "skin-on" to the search and found the
# plain SR belly (518 kcal/100 g); the Foundation row that says the skin
# (385) ranked below it.

SR_BELLY = usda("167812", "Pork, fresh, belly, raw", [portion(1, "4 oz", 113.0)],
                518.0, raw=True)
FOUNDATION_BELLY = usda("2727576", "Pork, belly, with skin, raw", [portion(1, "RACC", 26.0)],
                        385.0, raw=True, data_type="Foundation")
SR_BELLY["display_name"] = "Pork belly, raw"
FOUNDATION_BELLY["display_name"] = "Pork belly, with skin, raw"


@pytest.mark.parametrize("line, expected", [
    ("skin-on pork belly", FOUNDATION_BELLY),
    ("pork belly with skin", FOUNDATION_BELLY),
    # Not asked for: the plain belly, as before.
    ("pork belly", SR_BELLY),
    ("skinless pork belly", SR_BELLY),
])
def test_a_skin_on_line_takes_the_row_with_skin(line, expected):
    assert best(line, [SR_BELLY, FOUNDATION_BELLY], "lb") is expected


# ── Plain pork belly is skin-on (food_aliases, 13 Nov 2026) ────────────────
# "pork belly" and "pork bellies" are aliases of the Foundation belly with
# skin; "skinless pork belly" must not pick that alias up when the search
# leaves "skinless" out.

@pytest.mark.parametrize("line, expected", [
    ("pork belly", FOUNDATION_BELLY),
    ("pork bellies", FOUNDATION_BELLY),
    ("skinless pork belly", SR_BELLY),
])
def test_plain_pork_belly_is_the_skin_on_alias(line, expected, monkeypatch):
    import food_name_search
    aliases = dict(food_name_search._food_aliases())
    for name in ("pork belly", "pork bellies"):
        aliases[food_name_search.alias_key(name)] = 2727576
    monkeypatch.setattr(food_name_search, "_ALIASES", aliases)
    assert best(line, [SR_BELLY, FOUNDATION_BELLY], "lb") is expected
