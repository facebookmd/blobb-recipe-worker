"""Frying oil is counted as the share the food absorbs, not the pot.

"3 cups vegetable oil for frying" in a karaage logged 3/4 cup of oil a
serving (1,445 kcal). The parser marks frying-oil lines; the matcher swaps
each for the absorbed share: a percent of the fried food's raw weight by
coating (the app project's fry_types table, fry_rates.py; the tests use
conftest.py's), in tbsp, in an "Absorbed
oil" section tagged with the fry type; the rows it is a share of are marked
"fried", so the app can let the user change both.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import fry_rates
import parse_recipe
import recipe_matcher as matcher


@pytest.mark.parametrize("line, name", [
    ("3 cups vegetable oil for frying", "vegetable oil"),
    ("vegetable oil, for deep frying", "vegetable oil"),
    ("Neutral oil (canola or vegetable), for frying", "vegetable oil"),
    ("Oil for deep-frying", "vegetable oil"),
    ("1 quart peanut oil, for frying", "peanut oil"),
    ("oil for frying, as needed", "vegetable oil"),
    ("canola oil, for the fryer", "canola oil"),
    ("2 cups shortening, for deep frying", "shortening"),
])
def test_frying_oil_lines(line, name):
    parsed = parse_recipe.parse_ingredient_line(line)
    assert parsed["unit"] == parse_recipe.FRYING_OIL_UNIT
    assert parsed["ingredient"] == name


@pytest.mark.parametrize("line", [
    "1/2 cup oil for pan-frying",
    "1/2 cup vegetable oil for pan-frying",
    "1 cup oil, for shallow frying",
])
def test_pan_frying_oil_lines(line):
    assert parse_recipe.parse_ingredient_line(line)["unit"] == parse_recipe.PAN_FRYING_OIL_UNIT


@pytest.mark.parametrize("line, qty, unit, name", [
    # A little oil "for frying" stays in the dish: counted in full.
    ("1 tbsp oil for pan-frying", 1.0, "tbsp", "vegetable oil"),
    ("2 tbsp neutral oil, for frying", 2.0, "tbsp", "vegetable oil"),
    ("2 tbsp vegetable oil", 2.0, "tbsp", "vegetable oil"),
    ("3-4 cups neutral oil", 3.0, "cup", "neutral oil"),
])
def test_other_oil_lines_are_ingredients(line, qty, unit, name):
    parsed = parse_recipe.parse_ingredient_line(line)
    assert (float(parsed["qty"]), parsed["unit"], parsed["ingredient"]) == (qty, unit, name)


def test_deep_fried_food_is_not_frying_oil():
    parsed = parse_recipe.parse_ingredient_line("4 piece deep-fried tofu")
    assert parsed["unit"] != parse_recipe.FRYING_OIL_UNIT


@pytest.mark.parametrize("ingredients, fry_type", [
    (["pork loin chop", "all-purpose flour", "egg", "panko"], "breaded"),
    (["shrimp", "tempura flour", "ice water"], "battered"),
    (["fish fillet", "all-purpose flour", "egg"], "battered"),
    (["chicken thigh", "soy sauce", "potato starch"], "starch-dusted"),
    (["firm tofu", "cornstarch"], "starch-dusted"),
    (["chicken thigh", "salt"], "unbreaded"),
])
def test_fry_type_from_the_coating(ingredients, fry_type):
    assert matcher._fry_type(ingredients) == fry_type


# Live values (Supabase, 16 Oct 2026).
CHICKEN = matcher._build_supabase_usda_food(
    {"id": 1, "fdc_id": 173628, "source_set": "sr_legacy",
     "description": "Chicken, broilers or fryers, thigh, meat and skin, raw",
     "display_name": "Chicken thigh, meat and skin, raw", "calories_100g": 221},
    0, {1: [{"label": "thigh with skin", "grams": 194.0, "sequence_number": 1}]})
STARCH = matcher._build_supabase_usda_food(
    {"id": 2, "fdc_id": 2000001, "source_set": "sr_legacy",
     "description": "Potato starch", "display_name": "Potato starch",
     "calories_100g": 333},
    0, {2: [{"label": "tbsp", "grams": 12.0, "sequence_number": 1}]})
POTATO = matcher._build_supabase_usda_food(
    {"id": 4, "fdc_id": 170026, "source_set": "sr_legacy",
     "description": "Potatoes, russet, flesh and skin, raw",
     "display_name": "Russet potato, raw", "calories_100g": 79},
    0, {4: [{"label": "large", "grams": 369.0, "sequence_number": 1}]})
OIL = matcher._build_supabase_usda_food(
    {"id": 3, "fdc_id": 172370, "source_set": "sr_legacy",
     "description": "Oil, vegetable", "display_name": "Vegetable oil",
     "calories_100g": 884},
    0, {3: [{"label": "tbsp", "grams": 13.6, "sequence_number": 1},
            {"label": "cup", "grams": 218.0, "sequence_number": 2}]})
EGGPLANT = matcher._build_supabase_usda_food(
    {"id": 5, "fdc_id": 169228, "source_set": "sr_legacy",
     "description": "Eggplant, raw", "display_name": "Eggplant, raw",
     "calories_100g": 25},
    0, {5: [{"label": "eggplant, unpeeled", "grams": 458.0, "sequence_number": 1}]})
WRAPPER = matcher._build_supabase_usda_food(
    {"id": 6, "fdc_id": 2000002, "source_set": "sr_legacy",
     "description": "Spring roll wrapper", "display_name": "Spring roll wrapper",
     "calories_100g": 290},
    0, {6: [{"label": "wrapper", "grams": 12.0, "sequence_number": 1}]})
PORK = matcher._build_supabase_usda_food(
    {"id": 7, "fdc_id": 2000003, "source_set": "sr_legacy",
     "description": "Pork, ground, raw", "display_name": "Ground pork, raw",
     "calories_100g": 263},
    0, {7: [{"label": "oz", "grams": 28.35, "sequence_number": 1}]})
TILAPIA = matcher._build_supabase_usda_food(
    {"id": 8, "fdc_id": 2000004, "source_set": "sr_legacy",
     "description": "Fish, tilapia, raw", "display_name": "Tilapia, raw",
     "calories_100g": 96},
    0, {8: [{"label": "fillet", "grams": 116.0, "sequence_number": 1}]})
FOODS = {"chicken": CHICKEN, "starch": STARCH, "oil": OIL, "potato": POTATO,
         "eggplant": EGGPLANT, "wrapper": WRAPPER, "pork": PORK, "tilapia": TILAPIA}


def rows_for(tmp_path, monkeypatch, lines):
    def match(ingredient, *a, **k):
        food = next(f for key, f in FOODS.items() if key in ingredient)
        return food, 1.0, "high", None
    monkeypatch.setattr(matcher, "match_ingredient", match)
    # The live food_aliases name "vegetable oil" (26 Oct 2026); these foods
    # are FOODS'.
    monkeypatch.setattr(matcher, "_alias_match", lambda *a, **k: None)
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(lines, name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    return [r for r in matcher.build_output_rows(str(csv), [], 0.0)
            if r.get("_type") in ("data", "note")]


def test_karaage_keeps_8_percent_of_the_chicken(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Karaage", "Servings: 4",
        "2 bone-in skin-on chicken thigh",
        "1/4 cup potato starch",
        "3 cups vegetable oil for frying",
    ])
    [oil] = [r for r in rows if r["section"] == matcher.ABSORBED_OIL_SECTION]
    # 2 thighs (388 g) / 4 servings = 97 g; 8% = 7.76 g of oil = 0.57 tbsp.
    assert oil["fry_type"] == "starch-dusted"
    assert oil["unit_label"] == "tbsp"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(97 * 0.08, rel=0.01)
    # Not the pot: 3 cups / 4 servings would be 163 g.
    assert oil["portion_amt"] * oil["unit_grams"] < 10
    # The chicken is what it's a share of; the starch isn't.
    [chicken] = [r for r in rows if "chicken" in r["component_label"]]
    [starch] = [r for r in rows if "starch" in r["component_label"]]
    assert chicken.get("fried") and not starch.get("fried")


def oil_row(rows):
    [oil] = [r for r in rows if r["section"] == matcher.ABSORBED_OIL_SECTION]
    assert oil["_type"] == "data"
    return oil


def test_fries_are_thick_cut_potato(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Fries", "Servings: 2",
        "2 large russet potato",
        "4 cups oil for frying",
    ])
    oil = oil_row(rows)
    # 1 large potato (369 g) a serving; 5% = 18.5 g of oil.
    assert oil["fry_type"] == "thick-cut"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(369 * 0.05, rel=0.01)
    [potato] = [r for r in rows if "potato" in r["component_label"]]
    assert potato.get("fried")


def test_fatty_unbreaded_cut_starts_at_no_oil(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Fried chicken", "Servings: 2",
        "2 bone-in skin-on chicken thigh",
        "oil, for deep frying",
    ])
    # Skin-on cuts lose fat: no oil, nothing marked, the user can pick.
    oil = oil_row(rows)
    assert oil["fry_type"] == "unbreaded"
    assert oil["portion_amt"] == 0
    assert not any(r.get("fried") for r in rows)


def test_nothing_to_fry_starts_at_no_oil(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Starch crisps", "Servings: 2",
        "1/4 cup potato starch",
        "2 cups oil for frying",
    ])
    oil = oil_row(rows)
    assert oil["fry_type"] == "starch-dusted"
    assert oil["portion_amt"] == 0
    assert not any(r.get("fried") for r in rows)


def test_plain_fried_vegetables_keep_10_percent(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Su-age eggplant", "Servings: 2",
        "1 eggplant",
        "2 cups oil for frying",
    ])
    oil = oil_row(rows)
    # Half an eggplant (229 g) a serving; watery vegetables keep 10%.
    assert oil["fry_type"] == "unbreaded veg"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(229 * 0.10, rel=0.01)
    [eggplant] = [r for r in rows if "eggplant" in r["component_label"].lower()]
    assert eggplant.get("fried")


def test_meat_is_fried_before_vegetables(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Fried chicken and eggplant", "Servings: 2",
        "2 boneless chicken thigh",
        "1 eggplant",
        "2 cups oil for frying",
    ])
    oil = oil_row(rows)
    # Lean meat, unbreaded: 5% of the chicken only.
    assert oil["fry_type"] == "unbreaded"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(194 * 0.05, rel=0.01)


def test_a_bone_in_weight_fries_its_edible_part(tmp_path, monkeypatch):
    # The rates are per 100 g of edible food, like its calories: the oil
    # follows the thigh's edible weight, not the bone (28 Oct 2026).
    rows = rows_for(tmp_path, monkeypatch, [
        "Karaage", "Servings: 4",
        "1 lb bone-in skin-on chicken thigh",
        "1/4 cup potato starch",
        "3 cups vegetable oil for frying",
    ])
    [chicken] = [r for r in rows if "chicken" in r["component_label"]]
    assert "bone 17% left out" in chicken["notes"]
    chicken_grams = chicken["portion_amt"] * chicken["unit_grams"]
    oil = oil_row(rows)
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(chicken_grams * 0.08, rel=0.01)


def test_no_rates_means_no_guess(tmp_path, monkeypatch):
    def unavailable():
        raise fry_rates.FryTypesUnavailable("fry_types unreadable")
    monkeypatch.setattr(fry_rates, "load_fry_types", unavailable)
    with pytest.raises(fry_rates.FryTypesUnavailable):
        rows_for(tmp_path, monkeypatch, [
            "Karaage", "Servings: 4",
            "2 bone-in skin-on chicken thigh",
            "1/4 cup potato starch",
            "3 cups vegetable oil for frying",
        ])


@pytest.mark.live_fry_types
@pytest.mark.skipif(not os.environ.get("APP_SUPABASE_KEY"),
                    reason="needs APP_SUPABASE_KEY (the app project's fry_types)")
def test_live_fry_types_table():
    try:
        types = fry_rates.load_fry_types(force=True)
    except fry_rates.FryTypesUnavailable as e:
        if "fry_types" in str(e) and ("PGRST205" in str(e) or "404" in str(e)):
            pytest.skip("fry_types isn't created yet (blobbapp migration 20261028120000)")
        raise
    # Every type the matcher can pick, each a share of the food's weight.
    keys = {t["key"] for t in types}
    assert {"breaded", "battered", "starch-dusted", "unbreaded", "unbreaded veg",
            "thick-cut", "thin-sliced"} <= keys
    assert all(0 <= t["rate"] < 1 for t in types)
    assert [t["sort_order"] for t in types] == sorted(t["sort_order"] for t in types)


# ── RECIPE_RULES.md's table is written from fry_types ───────────────────────

def test_the_rules_table_is_written_between_its_markers():
    import sync_fry_rates
    from conftest import FRY_TYPES
    doc = sync_fry_rates.RULES.read_text(encoding="utf-8")
    once = sync_fry_rates.synced(doc, FRY_TYPES)
    assert sync_fry_rates.synced(once, FRY_TYPES) == once
    assert "| starch-dusted | 8% |" in once and "| fatty cut | 0% |" in once
    # Only the table changes.
    start = doc.index(sync_fry_rates.START)
    assert once[:start] == doc[:start]
    assert once[once.index(sync_fry_rates.END):] == doc[doc.index(sync_fry_rates.END):]


@pytest.mark.live_fry_types
@pytest.mark.skipif(not os.environ.get("APP_SUPABASE_KEY"),
                    reason="needs APP_SUPABASE_KEY (the app project's fry_types)")
def test_live_rules_table_matches_fry_types():
    import sync_fry_rates
    try:
        types = fry_rates.load_fry_types(force=True)
    except fry_rates.FryTypesUnavailable as e:
        if "PGRST205" in str(e) or "404" in str(e):
            pytest.skip("fry_types isn't created yet (blobbapp migration 20261028120000)")
        raise
    doc = sync_fry_rates.RULES.read_text(encoding="utf-8")
    assert sync_fry_rates.synced(doc, types) == doc, "run sync_fry_rates.py"


# ── Wrapped and pan-fried fish (28 Oct 2026) ────────────────────────────────

def test_a_wrapper_fries_the_whole_roll(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Lumpia", "Servings: 2",
        "8 oz ground pork",
        "1 eggplant",
        "10 spring roll wrapper",
        "3 cups oil for frying",
    ])
    oil = oil_row(rows)
    fried = [r for r in rows if r.get("fried")]
    # Wrapper and filling: 12% of all of it.
    assert oil["fry_type"] == "wrapped"
    assert {r["component_label"] for r in fried} == {"ground pork", "eggplant", "spring roll wrapper"}
    grams = sum(r["portion_amt"] * r["unit_grams"] for r in fried)
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(grams * 0.12, rel=0.01)


def test_unbreaded_fish_in_oil_for_pan_frying_is_pan_fried_fish(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Pan-fried tilapia", "Servings: 2",
        "2 tilapia fillet",
        "1/2 cup vegetable oil for pan-frying",
    ])
    oil = oil_row(rows)
    # One fillet (116 g) a serving; 8%.
    assert oil["fry_type"] == "pan-fried fish"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(116 * 0.08, rel=0.01)


def test_deep_fried_fish_stays_unbreaded(tmp_path, monkeypatch):
    rows = rows_for(tmp_path, monkeypatch, [
        "Fried tilapia", "Servings: 2",
        "2 tilapia fillet",
        "3 cups vegetable oil for deep frying",
    ])
    oil = oil_row(rows)
    assert oil["fry_type"] == "unbreaded"
    assert oil["portion_amt"] * oil["unit_grams"] == pytest.approx(116 * 0.05, rel=0.01)
