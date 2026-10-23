"""Shortcuts that sent a line to the wrong food (23 Oct 2026).

The generic-meat shortcut took any line with "chicken" in it to roasted
chicken breast: "chicken nuggets", "chicken salad", "chicken noodle soup"
(canned soup is about 40 kcal/100 g, the breast 165). Its exclusions matched
inside words, so "boneless skinless chicken pieces" missed it and became
breaded fried pieces. The cooked-rice default made "brown rice" white rice,
and "skim milk" found "Yogurt, plain, skim milk": USDA calls it nonfat.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe as parser
import recipe_matcher as matcher


@pytest.mark.parametrize("ingredient,meat,only", [
    ("chicken", "chicken", True),
    ("shredded cooked chicken", "chicken", True),
    ("boneless skinless chicken pieces", "chicken", True),
    ("grilled chicken", "chicken", True),
    ("chicken nuggets", "chicken", False),
    ("chicken salad", "chicken", False),
    ("chicken noodle soup", "chicken", False),
    ("rotisserie chicken", "chicken", False),
])
def test_the_generic_meat_shortcut_is_for_the_meat_alone(ingredient, meat, only):
    assert matcher._only_the_meat(ingredient, meat) is only


LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                          reason="needs SUPABASE_ANON_KEY (live Supabase)")


@LIVE
@pytest.mark.parametrize("line,expected", [
    ("1 lb chicken nuggets", "Chicken nuggets, from restaurant"),
    ("2 cup chicken salad", "Chicken salad spread"),
    ("1 can chicken noodle soup", "Soup, chicken noodle, canned"),
    ("1 cup brown rice", "Brown rice, long-grain, cooked"),
    ("2 cup cooked brown rice", "Brown rice, long-grain, cooked"),
    ("1 cup skim milk", "Nonfat milk, vitamins A and D added"),
    ("1 lb boneless skinless chicken pieces", "Chicken breast, skinless, roasted"),
    # Unchanged.
    ("1 lb chicken", "Chicken breast, skinless, roasted"),
    ("1 lb chicken thighs", "Chicken thigh, with skin, raw"),
    ("2 cup cooked rice", "White rice, long-grain, cooked, enriched"),
])
def test_a_shortcut_no_longer_takes_another_food(line, expected):
    row = parser.parse_ingredient_line(line)
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    matcher._MATCH_CACHE.clear()
    food = matcher.match_ingredient(row["ingredient"], rules, 0.45, "American",
                                    row["unit"], row["is_cooked"])[0]
    assert food is not None and food["display_name"] == expected
