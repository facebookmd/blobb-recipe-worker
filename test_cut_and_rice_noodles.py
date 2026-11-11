"""Two wrong foods found by the template calorie audit (11 Nov 2026).

"1 cup cut green beans" (bulalo, lumpiang sariwa, pancit bihon, pancit
canton) was the canned "CUT GREEN BEANS" product, 17 kcal/100 g: the name
kept "cut", and a product saying every word beat "Green beans, raw" (40).
"cut" is a cut word like "sliced": it leaves the food's name.

"cooked rice vermicelli" (pancit bihon, palabok) and "cooked rice noodles"
(pancit malabon) were cooked white rice, 130 kcal/100 g: INGREDIENT_REMAP's
"cooked rice" matched inside the longer name. Rice noodles cooked are 108.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe as parser
import recipe_matcher as matcher


@pytest.mark.parametrize("line, ingredient", [
    ("1 cup cut green beans", "green beans"),
    ("2 cup cut yardlong beans", "yardlong beans"),
    # A word that only starts with "cut" stays.
    ("4 veal cutlet", "veal cutlet"),
])
def test_cut_leaves_the_food_name(line, ingredient):
    assert parser.parse_ingredient_line(line)["ingredient"] == ingredient


@pytest.mark.parametrize("ingredient, remapped, cooked", [
    ("cooked rice vermicelli", "cooked rice noodles", True),
    ("rice vermicelli", "rice noodles", False),
    ("cooked rice noodles", "cooked rice noodles", True),
    # Plain rice is still the cooked rice entry.
    ("cooked rice", "white rice long grain cooked", True),
    ("cooked white rice", "white rice long grain cooked", True),
])
def test_a_rice_product_is_not_cooked_rice(ingredient, remapped, cooked):
    got, is_cooked = matcher._recipe_remap(ingredient, "Filipino", "cup", "cooked" in ingredient)
    assert (got, is_cooked) == (remapped, cooked)


def test_vermicelli_is_not_plain_rice():
    assert not matcher._rice_keyword("cooked rice vermicelli")
    assert matcher._rice_keyword("cooked short grain white rice")
