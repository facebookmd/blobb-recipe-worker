"""Prep words that make the product (23 Oct 2026).

"1 can diced tomatoes" was raw tomatoes, "2 cup mashed potatoes" raw
potatoes, "4 hard boiled egg" a raw egg, "2 cup fried rice" plain rice:
the search left the prep word out, the row naming it lost points for it,
and shortcuts (the potato pin, the egg, rice and generic-meat fast paths)
returned their food before any row was scored. And "1 cup sliced onion"
was weighed as chopped (160 g a cup, sliced is 115): the parser dropped
"sliced" before portions were picked.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe as parser
import recipe_matcher as matcher


# ── Parser: cut words stay for portion picking ─────────────────────────────

@pytest.mark.parametrize("line,ingredient,size_hint", [
    ("1 cup sliced onion", "onion", "sliced"),
    ("1 cup onion, thinly sliced", "onion", "sliced"),
    ("1 onion, diced", "onion", "diced"),
    ("2 medium carrots, peeled and diced", "carrots", "medium diced"),
    ("3 cloves garlic, minced", "garlic", "minced"),
    # Product words stay in the name, as before.
    ("1 cup grated parmesan", "grated parmesan", ""),
    ("1 cup diced onion", "diced onion", ""),
])
def test_cut_words_the_parser_drops_join_the_size_hint(line, ingredient, size_hint):
    row = parser.parse_ingredient_line(line)
    assert (row["ingredient"], row["size_hint"]) == (ingredient, size_hint)


# ── Preparations a shortcut's food must have ───────────────────────────────

def test_preparations_are_named_before_the_food():
    assert matcher._line_preparations("mashed potatoes") == {"mashed"}
    assert matcher._line_preparations("hard boiled egg") == {"boiled"}
    # After a comma it's an instruction: eggs to scramble.
    assert matcher._line_preparations("eggs, scrambled") == set()


def _food(name):
    return {"display_name": name, "raw_description": name}


def test_a_food_fits_a_preparation_it_names_or_a_cooking_word_when_cooked():
    raw_potato = _food("Potatoes, flesh and skin, raw")
    cooked_chicken = _food("Chicken, broilers or fryers, meat and skin, cooked, roasted")
    assert not matcher._fits_preparations(raw_potato, {"mashed"})
    assert matcher._fits_preparations(_food("Potatoes, mashed, home-prepared"), {"mashed"})
    # "grilled chicken" is cooked chicken; "fried chicken" is another food.
    assert matcher._fits_preparations(cooked_chicken, {"grilled"})
    assert not matcher._fits_preparations(cooked_chicken, {"fried"})
    assert not matcher._fits_preparations(_food("Egg, whole, raw, fresh"), {"boiled"})


def test_a_word_the_line_said_costs_a_row_nothing():
    diced = {"raw_description": "Tomatoes, canned, red, ripe, diced"}
    assert matcher._usda_variant_count("tomatoes", diced) == 1          # canned
    assert matcher._usda_variant_count("tomatoes", diced, said=frozenset({"canned", "diced"})) == 0
    assert matcher._is_unknown_qualifier("diced")
    assert not matcher._is_unknown_qualifier("diced", frozenset({"diced"}))


# ── Live matches ───────────────────────────────────────────────────────────

LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                          reason="needs SUPABASE_ANON_KEY (live Supabase)")


def _match(line):
    row = parser.parse_ingredient_line(line)
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    matcher._MATCH_CACHE.clear()
    food = matcher.match_ingredient(row["ingredient"], rules, 0.45, "American",
                                    row["unit"], row["is_cooked"])[0]
    return row, rules, food


@LIVE
@pytest.mark.parametrize("line,expected", [
    ("1 can diced tomatoes", "Diced ripe red tomatoes, canned"),
    ("2 cup mashed potatoes", "Potato, mashed"),
    ("4 hard boiled egg", "Hard-boiled egg"),
    ("2 cup fried rice", "Rice, fried, with chicken"),
    ("1 lb fried chicken", "Chicken, skinless, fried"),
    ("2 deviled eggs", "Egg, deviled"),
    ("1 fried egg", "Fried egg"),           # the "egg" boost rewrote it raw
    # Unchanged: no preparation, or one the food already has.
    ("2 eggs, scrambled", "Whole egg, raw"),
    ("1 cup grilled chicken", "Chicken breast, skinless, roasted"),
    ("2 potatoes", "White potatoes, flesh and skin, raw"),
    ("2 cup diced tomatoes", "Tomatoes, raw"),
])
def test_a_preparation_that_makes_the_product_finds_it(line, expected):
    food = _match(line)[2]
    assert food is not None and food["display_name"] == expected


@LIVE
@pytest.mark.parametrize("line,label,grams", [
    ("1 cup sliced onion", "1 cup, sliced", 115.0),
    ("1 cup onion, thinly sliced", "1 cup, sliced", 115.0),
    ("1 cup chopped onion", "1 cup, chopped", 160.0),
    ("1 onion, diced", '1 medium (2-1/2" dia)', 110.0),
])
def test_a_cut_word_picks_its_portion(line, label, grams):
    row, rules, food = _match(line)
    qty = float(row["qty"] or 1)
    portion = matcher.pick_best_portion(
        food, row["unit"], matcher.to_grams(qty, row["unit"], row["ingredient"]), qty,
        f"{row['ingredient']} {row['size_hint']}".strip(), rules)
    assert (portion["label"], portion["gram_weight"]) == (label, grams)
