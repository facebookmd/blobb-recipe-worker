"""Matching errors found in the American dry run (23 Oct 2026).

The parser cut "hoagie roll" and "pie crust" at "ie" and dropped "hot" from
"hot sauce"; "uncooked" rice, noodles and grits found cooked foods; plurals
ending in -es didn't meet their singular ("pickles"/"pickle"); counts took a
miniature, cracker-size or borrowed portion over the plain one; "1 serving
1/2 cup" read as a cup; "1 packet" took the first portion; and a chicken cut
or "whole" the parser moved into the unit left only "chicken" to search.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe as parser
import recipe_matcher as matcher
import template_refs as tref


def usda(fdc_id, name, portions=(), category="Baked Products", kcal=100.0):
    return {
        "source": "usda", "fdc_id": str(fdc_id), "display_name": name,
        "raw_description": name, "alt_names": [], "category": category,
        "data_type": "Survey (FNDDS)", "energy_kcal": kcal, "is_raw": False,
        "portions": [{"portion_id": f"{fdc_id}-{i}", "label": label, "gram_weight": grams,
                      "gram_col": "", "portion_idx": i}
                     for i, (label, grams) in enumerate(portions, start=1)],
    }


def parsed(line):
    row = parser.parse_ingredient_line(line)
    return row["unit"], row["ingredient"]


# ── Parser ──────────────────────────────────────────────────────────────────

def test_words_ending_in_ie_are_not_an_ie_clause():
    assert parsed("4 hoagie roll") == ("piece", "hoagie roll")
    assert parsed("2 pie crust") == ("piece", "pie crust")
    assert parsed("1 cup brownie mix")[1] == "brownie mix"


def test_example_clauses_are_still_stripped():
    assert parsed("1 tsp salt, e.g. kosher")[1] == "salt"
    assert parsed("1 tbsp oil, i.e. canola")[1] == "oil"
    assert parsed("2 cup flour such as bread flour")[1] == "flour"


def test_a_temperature_word_naming_the_food_stays():
    assert parsed("1/3 cup hot sauce")[1] == "hot sauce"
    assert parsed("8 hot dog bun")[1] == "hot dog bun"
    assert parsed("2 cup hot chocolate")[1] == "hot chocolate"
    assert parsed("1 cup iced tea")[1] == "iced tea"


def test_a_temperature_word_describing_the_food_goes():
    assert parsed("1 cup hot water")[1] == "water"
    assert parsed("2 cup cold water")[1] == "water"
    assert parsed("1 cup warm milk")[1] == "milk"


# ── Plurals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plural,singular", [
    ("pickles", "pickle"), ("apples", "apple"), ("sauces", "sauce"),
    ("olives", "olive"), ("tomatoes", "tomato"), ("peaches", "peach"),
    ("dishes", "dish"), ("berries", "berry"), ("noodles", "noodle"),
])
def test_a_plural_meets_its_singular(plural, singular):
    assert matcher._canonical_token(plural) == matcher._canonical_token(singular)


# ── Portions ────────────────────────────────────────────────────────────────

BUN = usda(2707657, "Roll, white, hamburger bun", [
    ("1 miniature/small hamburger bun", 28.0), ("1 hamburger bun", 52.0),
    ("Quantity not specified", 52.0)])
AVOCADO = usda(2709223, "Avocado, raw", [
    ("1 slice", 15.0), ("1 fruit", 150.0), ("1 cup", 150.0)], category="Fruits")
AVOCADO["portions"].append({"portion_id": "2709223-vol-2708960", "label": "1 piece",
                            "gram_weight": 30.0, "gram_col": "", "portion_idx": 4})
GYOZA = usda(1, "Gyoza wrappers", [("1 piece", 6.0), ("1 package", 280.0)])
CHEESE = usda(2705764, "Cheese, American", [
    ("1 cracker-size slice", 9.0), ("1 slice", 21.0), ("1 cup, shredded", 113.0)],
    category="Dairy and Egg Products")
ICE_CREAM = usda(167575, "Vanilla ice cream", [("1 serving 1/2 cup", 66.0)])
SOUP_MIX = usda(171165, "Onion soup mix, dry", [("1 serving 1 tbsp", 7.5), ("1 packet", 39.0)])


def pick(food, unit, ingredient):
    return matcher.pick_best_portion(food, unit, None, 1.0, ingredient)["label"]


def test_a_count_takes_the_plain_whole_item_over_a_miniature_one():
    assert pick(BUN, "piece", "hamburger roll") == "1 hamburger bun"


def test_a_whole_fruit_beats_a_slice_or_a_borrowed_piece():
    assert pick(AVOCADO, "piece", "avocado") == "1 fruit"
    assert pick(AVOCADO, "piece", "avocado large") == "1 fruit"


def test_a_food_counted_in_pieces_keeps_its_piece():
    assert pick(GYOZA, "piece", "gyoza wrapper") == "1 piece"


def test_a_slice_takes_the_plain_slice_over_a_cracker_size_one():
    assert pick(CHEESE, "slice", "American cheese") == "1 slice"


def test_a_borrowed_slice_is_the_plain_one():
    portion = matcher._density_portion(CHEESE, "slice", "American cheese")
    assert portion["label"] == "1 slice"


def test_one_serving_half_a_cup_is_half_a_cup():
    assert matcher._portion_label_qty("1 serving 1/2 cup") == 0.5
    assert matcher._portion_label_qty("1 10 Wrappers") == 10.0
    assert matcher._portion_label_qty("1 cup") == 1.0


def test_a_packet_line_takes_the_packet_portion():
    assert pick(SOUP_MIX, "pack", "onion soup mix") == "1 packet"


# ── Searches the parser's unit hid ──────────────────────────────────────────

def test_uncooked_rice_and_noodles_search_in_usda_words(monkeypatch):
    searched = []

    def fake_once(ingredient, *args, **kwargs):
        searched.append(ingredient)
        found = ingredient.startswith(("raw ", "dry "))
        return ({"fdc_id": "1", "display_name": ingredient} if found else None, 1.0, "high", None)

    monkeypatch.setattr(matcher, "_match_ingredient_once", fake_once)
    monkeypatch.setattr(matcher, "_respelled", lambda ingredient, *a: ingredient)
    matcher.match_ingredient("uncooked long grain white rice", [], unit="cup")
    matcher.match_ingredient("uncooked egg noodles", [], unit="cup")
    matcher.match_ingredient("uncooked grits", [], unit="cup")
    assert searched == ["raw long grain white rice", "dry egg noodles", "dry grits"]


def test_a_cut_or_whole_bird_in_the_unit_is_searched(monkeypatch):
    searched = []

    def fake_once(ingredient, *args, **kwargs):
        searched.append(ingredient)
        return ({"fdc_id": "1", "display_name": ingredient}, 1.0, "high", None)

    monkeypatch.setattr(matcher, "_match_ingredient_once", fake_once)
    monkeypatch.setattr(matcher, "_respelled", lambda ingredient, *a: ingredient)
    matcher.match_ingredient("bone-in skin-on chicken", [], unit="drumstick")
    matcher.match_ingredient("chicken", [], unit="whole")
    matcher.match_ingredient("onion", [], unit="whole")
    assert searched == ["bone-in skin-on chicken drumstick", "whole chicken", "onion"]


# ── Live matches (boosts.json rules) ────────────────────────────────────────

LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                          reason="needs SUPABASE_ANON_KEY (live Supabase)")


@LIVE
@pytest.mark.parametrize("line,expected", [
    ("4 hoagie roll", "Roll, white, hoagie, submarine"),
    ("2 pie crust", "Pie crust, refrigerated, unbaked"),
    ("4 bone-in skin-on chicken drumstick", "Chicken drumstick, with skin, raw"),
    ("1 whole chicken", "Roasting chicken, with skin, giblets, and neck, raw"),
    ("12 oz pork breakfast sausage", "Pork sausage, link/patty, unprepared"),  # raw
    ("3 cup clam juice", "CLAM JUICE BROTH"),
    ("3/4 cup uncooked grits", "Quick white corn grits, enriched, dry"),
    ("8 slice dill pickle", "Pickles, dill"),
    ("1 1/4 cup uncooked long grain white rice", "White rice, long-grain, raw, enriched"),
    ("3 cup uncooked egg noodles", "Egg noodles, dry, enriched"),
])
def test_american_lines_match_the_food(line, expected):
    row = parser.parse_ingredient_line(line)
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    matcher._MATCH_CACHE.clear()
    food = matcher.match_ingredient(row["ingredient"], rules, 0.45, "American",
                                    row["unit"], row["is_cooked"])[0]
    assert food is not None and food["display_name"] == expected


# ── Live matches (food_aliases rows, supabase-usda 20261023130000) ──────────

@LIVE
@pytest.mark.parametrize("line,expected,portion", [
    ("4 hamburger bun", "Roll, white, hamburger bun", "hamburger bun"),
    ("4 lb pork baby back ribs", "Pork back ribs, raw", None),
    ("1 3/4 cup canned pumpkin", "Pumpkin, canned, unsalted", "cup"),
    ("1/3 cup hot sauce", "Hot pepper sauce", None),
    ("1.5 cup semisweet chocolate chips", "Semisweet chocolate", "cup chips"),
    ("1/3 cup mini semisweet chocolate chips", "Semisweet chocolate", "cup mini chips"),
])
def test_american_synonyms_are_food_aliases(line, expected, portion):
    row = parser.parse_ingredient_line(line)
    matcher._FOOD_ALIASES.clear()
    matcher._FOOD_ALIASES_TRIED_AT = None
    if tref.template_key(row["ingredient"]) not in matcher._food_aliases():
        pytest.skip("food_aliases migration 20261023130000 not pushed yet")
    food, alias_portion = matcher._alias_match(row["ingredient"], row.get("size_hint", ""),
                                               row["unit"])
    assert food["display_name"] == expected
    if portion is None:
        assert alias_portion is None
    else:
        assert alias_portion is not None and alias_portion["label"].removeprefix("1 ").startswith(portion)
