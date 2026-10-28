#!/usr/bin/env python3
from __future__ import annotations
"""
recipe_matcher.py
-----------------
Matches recipe ingredients against the USDA food database (via Supabase):
food_name_search, the app's food search, names the foods, and the recipe
layer here (_match_ingredient_once) reads the line's amounts, units, cooked
or raw state and recipe conventions (boosts.json).

Usage:
    python recipe_matcher.py --recipes recipes.csv \
        [--boosts boosts.json] [--output templates_output.xlsx] \
        [--threshold 0.45]
"""

import argparse
import dataclasses
import statistics
import csv
import json
import os
import unicodedata
import re
import sys
import time
from pathlib import Path
from collections import Counter, defaultdict

import food_name_search
import fry_rates
import parse_recipe
import template_refs as tref

from supabase_food_source import (
    SupabaseLookupError,
    fail_on_request_errors,
    is_configured as supabase_is_configured,
    search_foods as supabase_search_foods,
    fetch_food_by_fdc_id as supabase_fetch_food_by_fdc_id,
    load_food_aliases,
    load_portions_for_food_ids,
    search_food_names_by_spelling as supabase_search_food_names_by_spelling,
)

# â”€â”€ built-in boost rules â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BUILTIN_BOOSTS = [
    {"trigger": "curry roux",      "boost": "GOLDEN CURRY", "fdc_id": "B_2031609", "weight": 0.95, "category": "japanese"},
    # Pinned: scored, "vegetable oil soybean" picked a 70%-fat margarine spread.
    # Bare "oil" only; other generic phrasings ("neutral oil", "salad oil")
    # are their own rules in boosts.json.
    {"trigger": "cooking oil",   "boost": "vegetable oil soybean", "fdc_id": "171411", "weight": 0.6},
    {"trigger": "oil",           "boost": "vegetable oil soybean", "fdc_id": "171411", "weight": 0.6,
     "exact": True},
    # Pinned: scored, the unspecific search text picked "Potatoes, red".
    {"trigger": "potato",        "boost": "potatoes flesh and skin raw", "fdc_id": "170028", "weight": 0.6,
     "exclude": ["potato starch","sweet","chip","crisp","flake","flour","fries",
                 "salad","instant","tots","hash"]},
    # Green, not the red pepper the rule below searches for.
    {"trigger": "green bell pepper", "fdc_id": "170427",                   "weight": 0.95},
    {"trigger": "bell pepper",   "boost": "sweet red pepper raw",        "weight": 0.6},
    # 170005, not the Foundation row 2727585: that one has no calories.
    {"trigger": "spring onion",  "boost": "scallions raw", "fdc_id": "170005", "weight": 0.9},
    {"trigger": "green onion",   "fdc_id": "170005",                     "weight": 0.9},
    {"trigger": "scallion",      "fdc_id": "170005",                     "weight": 0.9},
    {"trigger": "scallions",     "fdc_id": "170005",                     "weight": 0.9},
    {"trigger": "onion",         "boost": "onions raw",                  "weight": 0.6},
    {"trigger": "garlic chives", "boost": "chives raw",                  "weight": 0.9},
    {"trigger": "bay leaf",      "boost": "bay leaf",                    "weight": 0.6},
    {"trigger": "chili pepper",  "boost": "hot red chili pepper",        "weight": 0.6},
    {"trigger": "chilli",        "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chillies",      "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chilis",        "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chili",         "boost": "hot red chili pepper",        "weight": 0.8,
     "exclude": ["powder","seasoning","sauce","oil","paste","flakes","con carne"]},
    {"trigger": "beef broth",    "boost": "beef broth canned",           "weight": 0.6},
    {"trigger": "chicken broth", "boost": "chicken broth low sodium",    "weight": 0.6},
    {"trigger": "liver spread",  "boost": "liverwurst spread",           "weight": 0.6},
    {"trigger": "chicken pate",  "boost": "chicken liver pate canned",   "weight": 0.9},
    {"trigger": "duck pate",     "boost": "chicken liver pate canned",   "weight": 0.7},
    {"trigger": "pork pate",     "boost": "chicken liver pate canned",   "weight": 0.7},
    {"trigger": "pork bouillon", "boost": "beef bouillon cubes dry",     "weight": 0.6},
    {"trigger": "hotdog",        "boost": "frankfurter meat",            "weight": 0.6},
    {"trigger": "unsalted peanut", "boost": "peanuts without salt",      "weight": 0.9,
     "exclude": ["butter","flour","sauce","oil"]},
    {"trigger": "peanut, unsalted", "boost": "peanuts without salt",     "weight": 0.9,
     "exclude": ["butter","flour","sauce","oil"]},
    {"trigger": "peanuts unsalted", "boost": "peanuts without salt",     "weight": 0.9,
     "exclude": ["butter","flour","sauce","oil"]},
    {"trigger": "unsalted butter","boost": "butter unsalted",            "weight": 0.9},
    {"trigger": "whole-egg mayo", "boost": "mayonnaise",                 "weight": 0.9},
    {"trigger": "whole egg mayo", "boost": "mayonnaise",                 "weight": 0.9},
    {"trigger": "whole-egg mayonnaise","boost": "mayonnaise",            "weight": 0.9},
    {"trigger": "whole egg mayonnaise","boost": "mayonnaise",            "weight": 0.9},
    {"trigger": "butter",        "boost": "butter salted", "fdc_id": "173410", "weight": 0.7,
     "exclude": ["unsalted","peanut","almond","cashew","sunflower","cocoa","shea",
                 "buttermilk","butternut","butterscotch","butterhead","butter bean"]},
    # 80/20 is the everyday supermarket grind; scored, "ground beef" lands on
    # the 95/5 row or an FNDDS "Beef, ground" with only a cubic-inch portion.
    {"trigger": "ground beef",   "boost": "beef ground 80 lean raw", "fdc_id": "174036", "weight": 0.7,
     "exclude": ["pork","lean","90%","93%","95%","85%","cooked","browned","crumbles"]},
    {"trigger": "minced beef",   "boost": "beef ground 80 lean raw", "fdc_id": "174036", "weight": 0.7,
     "exclude": ["pork","lean","cooked","browned"]},
    {"trigger": "beef mince",    "boost": "beef ground 80 lean raw", "fdc_id": "174036", "weight": 0.7,
     "exclude": ["pork","lean","cooked","browned"]},
    # Plain white bread isn't in the first 160 search hits for "bread", so
    # scoring picks among egg, cheese and Italian breads. Bare "bread" only.
    {"trigger": "bread",         "boost": "bread white commercially prepared", "fdc_id": "174924",
     "weight": 0.7, "exact": True},
    {"trigger": "coriander",     "boost": "cilantro raw",                "weight": 0.8,
     "exclude": ["ground","dried","seed","seeds","powder","spice"]},
    {"trigger": "ground coriander","boost": "coriander seed",            "weight": 0.9},
    {"trigger": "coriander seed", "boost": "coriander seed",             "weight": 0.9},
    # Spice/herb boosts â€” single-word names score low against USDA's
    # "X, ground" / "X, dried" convention; boost to the expected form.
    {"trigger": "turmeric",      "boost": "turmeric ground",             "weight": 0.9},
    {"trigger": "allspice",      "boost": "allspice ground",             "weight": 0.9},
    {"trigger": "ginger",        "boost": "ginger root",                "weight": 0.9,
     "exclude": ["ground","dried","powder","ale","beer","snap","bread"]},
    {"trigger": "clove",         "boost": "cloves ground",               "weight": 0.9},
    {"trigger": "cayenne",       "boost": "cayenne pepper",              "weight": 0.9},
    {"trigger": "cumin",         "boost": "cumin seed",                  "weight": 0.9},
    {"trigger": "daikon",        "boost": "radishes oriental raw", "fdc_id": "168451", "weight": 0.9},
    {"trigger": "flour",         "boost": "all-purpose flour",           "weight": 0.8,
     "exclude": ["rice","corn","almond","coconut","oat","bread","cake","self","rye",
                 "buckwheat","whole","00","arrowroot","tapioca","chickpea","cassava"]},
    {"trigger": "white bread",   "boost": "White bread",                 "weight": 0.9,
     "exclude": ["crumb","stuffing","pudding"]},
    {"trigger": "large egg",     "boost": "whole egg large",             "weight": 0.9},
    # Japanese cooking essentials — short names with no USDA standard entry;
    # boost to the branded/common name so the token index finds them.
    {"trigger": "mirin",         "boost": "mirin sweet rice wine",       "weight": 0.9,
     "exclude": ["vinegar"]},
    {"trigger": "sake",          "boost": "sake rice wine",              "weight": 0.9,
     "exclude": ["vinegar","salmon"]},
    {"trigger": "katsuobushi",   "boost": "bonito flakes",               "weight": 0.9},
    {"trigger": "kombu",         "boost": "kelp", "fdc_id": "168457", "weight": 0.9},
    {"trigger": "ponzu",         "boost": "ponzu sauce",                 "weight": 0.9},
    {"trigger": "furikake",      "boost": "furikake seasoning",          "weight": 0.9},
    {"trigger": "panko",         "boost": "panko breadcrumbs",           "weight": 0.9},
    {"trigger": "nori",          "boost": "laver seaweed", "fdc_id": "168458", "weight": 0.9,
     "exclude": ["furikake"]},
    {"trigger": "miso",          "boost": "miso paste",                  "weight": 0.9,
     "exclude": ["soup"]},
    {"trigger": "togarashi",     "boost": "shichimi togarashi",          "weight": 0.9},
]
PREP_WORDS = {
    "chopped","sliced","diced","minced","frozen","raw","fresh","cooked","boiled","mashed",
    "fried","grilled","roasted","baked","dried","ground","shredded","grated","crushed",
    "peeled","ripe","unripe","blanched","seasoned","sauteed","sauted","squeezed",
    "boneless","skinless","lean","extra","finely","roughly","thinly","thin","thick",
}


# "Ground" names a product for meat (USDA "Ground beef, raw") but only a form
# for spices, where stripping it keeps "ground pepper" on "Black pepper".
# With a meat word present, keep it and spell "mince"/"minced" as "ground".
GROUND_MEAT_WORDS = {"beef", "pork", "chicken", "turkey", "lamb", "veal"}
MINCE_WORDS = {"ground", "mince", "minced"}


PORTION_UNIT_KEYWORDS = {
    # Volumetric
    "tbsp":["tablespoon","tbsp"],"tablespoon":["tablespoon","tbsp"],
    "tsp":["teaspoon","tsp"],"teaspoon":["teaspoon","tsp"],
    "cup":["cup"],"cups":["cup"],
    # Weight
    "oz":["ounce","oz"],"lb":["pound","lb"],"g":["gram","100g","100 g"],
    # Countable â€” generic
    # "1 fruit without refuse" is one mango (336 g).
    "piece":["medium","large","small","piece","unit","each","item","wrapper","wrappers","whole","fruit"],
    "clove":["clove"],
    "bunch":["bunch"],
    # A stalk is one whole stalk: green onion's portions are "1 medium",
    # "1 large", "1 small" and "1 cup, chopped", and with no keyword the
    # first one, the cup, was used (6x a stalk). "whole" means the same.
    "stalk":["stalk","rib","medium","large","small","whole","piece"],
    "stalks":["stalk","rib","medium","large","small","whole","piece"],
    "whole":["medium","large","small","whole","piece","fruit"],
    "sprig":["sprig"],
    "sprigs":["sprig"],
    "slice":["slice"],
    "can":["can"],
    # Countable â€” shape/cut
    "stick":["stick"],
    "strip":["strip","strips"],
    "leaf":["leaf","leaves"],
    "spear":["spear"],
    "head":["head"],
    "ear":["ear","cob"],
    "fillet":["fillet","filet"],
    # A sheet of crackers is USDA's "1 large rectangular piece or 2 squares".
    "sheet":["sheet","piece","square","rectangular"],
    "sheets":["sheet","piece","square","rectangular"],
    "link":["link"],
    "links":["link"],
    "cube":["cube"],
    "steak":["steak"],
    "patty":["patty"],
    "chop":["chop"],
    "wrapper":["wrapper","wrappers"],
    "drumstick":["drumstick"],
    "thigh":["thigh"],
    "breast":["breast", "piece"],
    "wing":["wing", "piece"],
    "serving":["serving","per serving"],
}

FISH_FILLET_HINTS = (
    "fish", "seafood", "eel", "mackerel", "salmon", "tuna", "cod", "trout",
    "haddock", "pollock", "sardine", "anchovy", "herring", "catfish", "tilapia",
    "snapper", "halibut", "bass", "sole", "flounder", "swordfish", "mullet",
    "perch", "rockfish", "grouper", "monkfish", "whitefish", "pomfret",
    "yellowtail", "barramundi", "sturgeon",
)


def _is_fish_or_seafood_name(text: str) -> bool:
    low = text.lower()
    return any(
        re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", low)
        for term in FISH_FILLET_HINTS
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Text utilities
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def _ordered_query_tokens(query_tokens, index):
    """Process rarer query tokens first so broad terms cannot crowd out
    specific hits when candidate lists are truncated."""
    return sorted(query_tokens, key=lambda tok: (len(index.get(tok, [])), tok))


def _token_in_label(token: str, label_tokens: set[str]) -> bool:
    """
    Match a token against a label token set, allowing a simple singular/plural
    equivalence so wrapper/wrappers and seed/seeds behave as the same noun.
    """
    token = _canonical_token(token)
    label_tokens = {_canonical_token(t) for t in label_tokens}
    if token in label_tokens:
        return True
    if token.endswith("s") and token[:-1] in label_tokens:
        return True
    if f"{token}s" in label_tokens:
        return True
    return False


def _canonical_token(token: str) -> str:
    """
    Collapse simple singular/plural variants so almonds/almond and
    wrappers/wrapper compare the same way in indexing and scoring.
    """
    t = token.lower().strip()
    if len(t) <= 3:
        return t
    if t == "powdered":
        return "powder"
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    # "-es" is a plural ending only after o, ch, sh, x, z (tomatoes, peaches);
    # elsewhere the e is the word's own: "pickles" became "pickl" while
    # "pickle" stayed "pickle", so "dill pickle" lost USDA's "Pickles, dill"
    # to a branded product (23 Oct 2026).
    if len(t) > 4 and t.endswith(("oes", "ches", "shes", "xes", "zes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


# Tokens that are usually descriptive but not distinctive enough on their own.
# If a query contains a distinctive token, we prefer candidates that share it
# instead of letting a generic overlap like "flakes" dominate the score.
GENERIC_QUERY_TOKENS = {
    "flakes", "flakes", "powder", "powders", "paste", "sauce", "sauces",
    "oil", "oils", "extract", "extracts", "seasoning", "seasonings",
    "mix", "mixes", "blend", "blends", "style", "flavored", "flavour",
    "flavor", "dried", "ground", "chopped", "sliced", "crushed", "fresh",
    "raw", "cooked", "organic", "natural",
}


def _one_edit_apart(a: str, b: str) -> bool:
    """Return True when two strings differ by exactly one insert/delete/substitute."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def _strip_words(text, words):
    tokens = [t for t in re.split(r"[\s,/\-]+", text.lower()) if t]
    if GROUND_MEAT_WORDS & set(tokens):
        tokens = ["ground" if t in MINCE_WORDS else t for t in tokens]
        words = words - MINCE_WORDS
    kept = [t for t in tokens if t not in words]
    return " ".join(kept) if kept else text.lower()

def strip_prep(text):
    return _strip_words(text, PREP_WORDS)


def normalise(text):
    # Accents fold to plain letters first: USDA spells it "Tomato purée", and
    # stripping the é outright left "pur e", which never matched "puree".
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9 ]"," ",folded.lower()).strip()


COLOR_WORDS = {
    "red", "green", "white", "black", "brown", "yellow", "purple",
    "orange", "pink", "blue", "golden",
}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Unit conversion
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def to_grams(qty, unit, ingredient):
    u = unit.lower().strip()
    # Weight units â€” exact conversions.
    if u in ("g","gram","grams"):  return qty
    if u == "kg":                   return qty * 1000
    if u == "oz":                   return qty * 28.35
    if u == "lb":                   return qty * 453.6
    if u in ("pinch", "pinches"):   return qty * 0.5
    # ml is the one volumetric unit where 1ml = 1g is reliable (water density).
    if u == "ml":                   return qty
    # All other volumetric units (tbsp, tsp, cup, fl oz, â€¦) and countables
    # return None â€” density varies too much per food to assume water-equivalent.
    # Portion selection uses the food's actual gram_weight from the DB instead.
    return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# USDA database loader
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class USDAIndex:
    """
    USDA food list with a tokenâ†’[idx] inverted index so the scorer can touch a
    small candidate subset instead of scanning all foods for every ingredient.
    """
    __slots__ = ("foods", "_index", "_by_id")

    def __init__(self):
        self.foods: list[dict] = []
        self._index: dict[str, list[int]] = {}
        self._by_id: dict[str, dict] = {}

    def __len__(self):
        return len(self.foods)

    def __iter__(self):
        return iter(self.foods)

    def __getitem__(self, idx):
        return self.foods[idx]

    def _tokens(self, text: str) -> set[str]:
        return {_canonical_token(t) for t in normalise(text).split() if len(t) >= 2}

    def add(self, food: dict):
        idx = len(self.foods)
        self.foods.append(food)
        self._by_id[food["fdc_id"]] = food
        for tok in self._tokens(food["display_name"]):
            self._index.setdefault(tok, []).append(idx)
        for alt in food.get("alt_names", []):
            for tok in self._tokens(alt):
                self._index.setdefault(tok, []).append(idx)

    def get(self, fdc_id: str, fetch: bool = True) -> dict | None:
        """
        Food by FDC ID. Per-ingredient indexes hold only that ingredient's
        search results, so a pinned ID is often absent; fetch it directly.
        """
        food = self._by_id.get(fdc_id)
        if food is None and fetch and fdc_id:
            food = _fetch_food_by_fdc_id(str(fdc_id))
        return food

    def candidates(self, search: str) -> list[dict]:
        query_tokens = self._tokens(search)
        if not query_tokens:
            return self.foods
        ordered_tokens = _ordered_query_tokens(query_tokens, self._index)
        seen: set[int] = set()
        hits: list[int] = []
        for tok in ordered_tokens:
            for idx in self._index.get(tok, []):
                if idx not in seen:
                    seen.add(idx)
                    hits.append(idx)
        if not hits:
            for tok in ordered_tokens:
                for bi in {tok[i:i+2] for i in range(len(tok)-1)}:
                    for idx in self._index.get(bi, []):
                        if idx not in seen:
                            seen.add(idx)
                            hits.append(idx)
        return [self.foods[i] for i in hits[:2000]] if hits else []


def _row_text(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _portion_label(portion_row: dict) -> str:
    """
    Portion label with its amount, e.g. "4 oz" — the same text the app shows
    (FoodPortion.displayServingLabel). Supabase keeps the amount in `value`
    and the unit in `label`; reading `label` alone gave "oz" for a 113 g
    portion, and the portion maths read that as one ounce.
    """
    label = _row_text(portion_row, "label")
    value = portion_row.get("value")
    try:
        value_num = float(value) if value is not None else None
    except (TypeError, ValueError):
        value_num = None
    if label and value_num is not None and not re.match(r"^\d", label):
        value_text = str(int(value_num)) if value_num == int(value_num) else f"{value_num:g}"
        return f"{value_text} {label}"
    return _row_text(portion_row, "description", "label")


def _portion_display_label(portion_row: dict, label: str) -> str:
    """[label] (from [_portion_label]) with the unit's clean name from the
    USDA project's display_label: "1 medium" for 'medium (2-1/2" dia)', "2
    piece, cooked" for "2 piece, cooked, excluding refuse (yield from 1 lb
    raw meat with refuse)". The count stays in front, as a whole, decimal or
    fraction ("1/2 English muffin" -> "1/2 English muffin"); the import
    divides it out. [label] when the row has no display_label (RACC)."""
    display = _row_text(portion_row, "display_label")
    if not display:
        return label
    count = re.match(r"^(\d+(?:\.\d+)?|\d+/\d+)\s+", label)
    return f"{count.group(1)} {display}" if count else display


def _build_supabase_usda_food(row: dict, row_index: int, portions_by_food_id: dict[int, list[dict]]) -> dict | None:
    source_set = _row_text(row, "source_set").lower()
    if source_set == "branded":
        return None

    food_id = row.get("id")
    try:
        food_id_int = int(food_id)
    except (TypeError, ValueError):
        return None

    fdc_id = _row_text(row, "fdc_id")
    if not fdc_id:
        return None

    display_name = _row_text(row, "display_name", "description")
    if not display_name:
        return None

    alt_names = []
    for candidate in (
        _row_text(row, "ingredients"),
        _row_text(row, "scientific_name"),
        _row_text(row, "brand_owner"),
        _row_text(row, "category"),
        _row_text(row, "household_serving_full_text"),
    ):
        if candidate and candidate not in alt_names:
            alt_names.append(candidate)

    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("foodCategory", "brandedFoodCategory"):
            candidate = _row_text(payload, key)
            if candidate and candidate not in alt_names:
                alt_names.append(candidate)

    portions = []
    for idx, portion_row in enumerate(portions_by_food_id.get(food_id_int, []), start=1):
        label = _portion_label(portion_row)
        grams = portion_row.get("grams")
        try:
            grams_val = float(grams) if grams is not None else None
        except (TypeError, ValueError):
            grams_val = None
        if not label or grams_val is None:
            continue
        portions.append({
            "portion_id": f"{fdc_id}-{idx}",
            "label": label,
            "gram_weight": grams_val,
            "gram_col": "",
            "portion_idx": idx,
            # The template's unit_label: the matcher reads `label`, the app
            # shows this. Kept with the label it belongs to, so a portion
            # derived from this one under a new label doesn't take it.
            "_display": (label, _portion_display_label(portion_row, label)),
        })

    try:
        energy_kcal = float(row.get("calories_100g") or 0.0)
    except (TypeError, ValueError):
        energy_kcal = 0.0

    category = _row_text(row, "category")
    if not category and isinstance(payload, dict):
        category = _row_text(payload, "foodCategory", "brandedFoodCategory")
    raw_hint = " ".join(
        part for part in (
            display_name,
            _row_text(row, "description"),
            category,
            _row_text(row, "ingredients"),
        ) if part
    ).lower()
    is_raw = any(
        token in raw_hint
        for token in (" raw", " uncooked", " unprepared", " fresh", " fresh ")
    ) or raw_hint.startswith("raw ")

    # The raw USDA description ("Salt, table, iodized"), which the search's
    # head rules read; display_name may reorder it ("Iodized salt").
    raw_description = _row_text(row, "description")

    return {
        "source": "usda",
        "row": row_index,
        "fdc_id": fdc_id,
        "display_name": display_name,
        "raw_description": raw_description,
        "alt_names": alt_names,
        "category": category,
        "data_type": _row_text(row, "data_type"),
        "energy_kcal": energy_kcal,
        "is_raw": is_raw,
        "portions": portions,
    }


BRANDED_SERVING_UNITS = {"g", "grm", "gram", "grams", "ml", "mlt"}
WEIGHT_LABEL_RE = re.compile(r"\b(?:g|grm|grams?|mg|kg|oz|onz|ounces?|lbs?)\b", re.IGNORECASE)
# A portion that is a plain weight: "4 oz", "100 g" (not "1 chop (151 g)").
WEIGHT_PORTION_LABEL_RE = re.compile(
    r"^\s*[\d./]+\s*(?:g|grams?|mg|kg|oz|ounces?|lbs?)\b", re.IGNORECASE)


# ml in one labelled "cup" that is a measuring cup: the FDA label cup (240),
# the US cup (236.6) and the metric cup (250). In live branded data (11 Oct
# 2026) 99% of ml "cup" servings fall here; the rest (108, 160, 50 ml) are
# the cup a food is sold in.
MEASURING_CUP_ML = (230.0, 250.0)
_CUP_HOUSEHOLD_RE = re.compile(r"^(\d+(?:\.\d+)?|\d+/\d+)\s*cups?\b")


def _is_container_cup(household: str, serving: float, serving_unit: str) -> bool:
    """A household "cup" (household "1 cup", serving 108 ml) that isn't a
    measuring cup. Only servings in ml can tell; a gram serving is trusted."""
    m = _CUP_HOUSEHOLD_RE.match(household)
    if not m or serving_unit not in ("ml", "mlt"):
        return False
    text = m.group(1)
    if "/" in text:
        num, den = text.split("/")
        qty = float(num) / float(den) if float(den) else 0.0
    else:
        qty = float(text)
    if qty <= 0:
        return False
    low, high = MEASURING_CUP_ML
    return not low <= serving / qty <= high


def _branded_label_serving(row: dict, fdc_id: str) -> dict | None:
    """
    The package label serving of a branded food, from the foods row itself
    (serving_size, serving_size_unit, household_serving_full_text). Branded
    foods have no food_portions rows, so without this "2 tbsp gyoza sauce"
    fell back to 2 x 100 g. FDC's per-100 basis follows the serving unit,
    so a 30 ml serving weighs 30 "grams" against calories_100g.

    The household text is the label when it names a volume or a count
    ("2 tbsp", "1 bar"); a weight ("0.28 oz", "4 GRM") becomes "1 serving"
    so it is never read as a volume. A "cup" given in ml that isn't a
    measuring cup (MEASURING_CUP_ML) is the cup it's sold in (Dole Whip:
    "1 cup" = 108 ml) and becomes "1 container".
    """
    unit = _row_text(row, "serving_size_unit").lower()
    try:
        grams = float(row.get("serving_size") or 0.0)
    except (TypeError, ValueError):
        return None
    if unit not in BRANDED_SERVING_UNITS or grams <= 0:
        return None
    household = " ".join(_row_text(row, "household_serving_full_text").lower().split())
    names_measure = bool(household and re.match(r"^\d", household) and not WEIGHT_LABEL_RE.search(household))
    # A 100 g serving is the per-100 g basis again, unless the label says
    # what it measures: "0.5 cup" (100 g) of young coconut was dropped, and
    # a cup of it estimated at 240 g (27 Oct 2026).
    if abs(grams - 100.0) < 0.001 and not names_measure:
        return None
    if not names_measure:
        household = "1 serving"
    elif _is_container_cup(household, grams, unit):
        household = "1 container"
    return {
        "portion_id": f"B_{fdc_id}-1",
        "label": household,
        "gram_weight": grams,
        "portion_idx": 1,
    }


_PACKAGE_GRAMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|grm|gram|grams|ml|mlt)\b", re.I)
_PACKAGE_UNITS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|lbs?|oz|onz|ounces?)\b", re.I)
_PACKAGE_UNIT_GRAMS = {"kg": 1000.0, "lb": 453.59237, "lbs": 453.59237,
                       "oz": 28.349523125, "onz": 28.349523125,
                       "ounce": 28.349523125, "ounces": 28.349523125}


def _package_grams(package_weight: str) -> float | None:
    """A branded food's label package size in grams: "1.4 oz/40 g" -> 40
    (the label's own grams first), "32 ONZ" -> 907. None when unreadable."""
    text = (package_weight or "").strip()
    m = _PACKAGE_GRAMS_RE.search(text)
    if m and float(m.group(1)) > 0:
        return float(m.group(1))
    m = _PACKAGE_UNITS_RE.search(text)
    if m and float(m.group(1)) > 0:
        return float(m.group(1)) * _PACKAGE_UNIT_GRAMS[m.group(2).lower()]
    return None


def _build_supabase_branded_food(row: dict, row_index: int, portions_by_food_id: dict[int, list[dict]]) -> dict | None:
    if _row_text(row, "source_set").lower() != "branded":
        return None

    food_id = row.get("id")
    try:
        food_id_int = int(food_id)
    except (TypeError, ValueError):
        return None

    fdc_id = _row_text(row, "fdc_id")
    if not fdc_id:
        return None

    display_name = _row_text(row, "display_name", "description")
    item_name = _row_text(row, "description", "display_name")
    if not display_name and not item_name:
        return None
    if not display_name:
        display_name = item_name
    if not item_name:
        item_name = display_name

    try:
        energy_kcal = float(row.get("calories_100g") or 0.0)
    except (TypeError, ValueError):
        energy_kcal = 0.0

    portions = [{
        "portion_id": f"B_{fdc_id}-0",
        "label": "100g",
        "gram_weight": 100.0,
        "portion_idx": 0,
    }]

    for idx, portion_row in enumerate(portions_by_food_id.get(food_id_int, []), start=1):
        label = _portion_label(portion_row)
        grams = portion_row.get("grams")
        try:
            grams_val = float(grams) if grams is not None else None
        except (TypeError, ValueError):
            grams_val = None
        if not label or grams_val is None:
            continue
        label_low = label.lower()
        if abs(grams_val - 100.0) < 0.001 and ("100g" in label_low or "100 g" in label_low):
            continue
        portions.append({
            "portion_id": f"B_{fdc_id}-{idx}",
            "label": label,
            "gram_weight": grams_val,
            "portion_idx": idx,
            "_display": (label, _portion_display_label(portion_row, label)),
        })

    if len(portions) == 1:
        serving = _branded_label_serving(row, fdc_id)
        if serving:
            portions.append(serving)

    raw_description = _row_text(row, "description")

    return {
        "source": "branded",
        "row": row_index,
        "fdc_id": f"B_{fdc_id}",
        "display_name": display_name,
        "raw_description": raw_description,
        "item_name": item_name,
        "category": _row_text(row, "brand_owner", "category"),
        "energy_kcal": energy_kcal,
        "portions": portions,
        "package_grams": _package_grams(_row_text(row, "package_weight")),
        # The label's own serving ("2 ONZ", 56 g), for _typical_branded.
        "serving_text": _row_text(row, "household_serving_full_text"),
        "serving_grams": row.get("serving_size"),
    }


# ── Per-ingredient search (queries Supabase per-ingredient like the app) ──────

# Cache of per-ingredient USDAIndex objects so repeated ingredients don't
# re-query Supabase within the same run.
_INGREDIENT_INDEX_CACHE: dict[tuple[str, str | None], "USDAIndex"] = {}


def _search_and_build_index(
    query: str,
    source_set: str | None = None,
    limit: int = 160,
) -> USDAIndex:
    """
    Search Supabase for foods matching *query* (FTS + ilike fallback),
    fetch portions for the returned food IDs, and build a small USDAIndex.

    This mirrors the app's FoodDatabase.search() pattern — only the foods
    relevant to the current ingredient are fetched, not the entire database.
    """
    cache_key = (query.strip().lower(), source_set)
    cached = _INGREDIENT_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows = supabase_search_foods(query, source_set=source_set, limit=limit)
    if not rows:
        idx = USDAIndex()
        _INGREDIENT_INDEX_CACHE[cache_key] = idx
        return idx

    # Collect food IDs for portion lookup
    food_ids = []
    for r in rows:
        fid = r.get("id")
        if fid is not None:
            try:
                food_ids.append(int(fid))
            except (TypeError, ValueError):
                pass

    portions_by_fid = load_portions_for_food_ids(food_ids) if food_ids else {}

    builder = (_build_supabase_branded_food if source_set == "branded"
               else _build_supabase_usda_food)

    index = USDAIndex()
    for i, row in enumerate(rows):
        food = builder(row, i, portions_by_fid)
        if food is not None:
            index.add(food)

    _INGREDIENT_INDEX_CACHE[cache_key] = index
    return index


_FDC_FETCH_CACHE: dict[str, dict | None] = {}


def _fetch_food_by_fdc_id(fdc_id: str) -> dict | None:
    """Build one food dict straight from Supabase by FDC ID ("B_" = branded)."""
    if fdc_id in _FDC_FETCH_CACHE:
        return _FDC_FETCH_CACHE[fdc_id]
    branded = fdc_id.startswith("B_")
    raw_id = fdc_id[2:] if branded else fdc_id
    food = None
    try:
        row = supabase_fetch_food_by_fdc_id(int(raw_id), branded=branded)
    except ValueError:
        row = None
    if row is not None:
        portions_by_fid = {}
        try:
            portions_by_fid = load_portions_for_food_ids([int(row["id"])])
        except (KeyError, TypeError, ValueError):
            pass
        builder = _build_supabase_branded_food if branded else _build_supabase_usda_food
        food = builder(row, 0, portions_by_fid)
    _FDC_FETCH_CACHE[fdc_id] = food
    return food


_FOOD_ALIASES: dict[str, dict] = {}
_FOOD_ALIASES_TRIED_AT: float | None = None
_FOOD_ALIASES_RETRY_SECONDS = 600


def _food_aliases() -> dict[str, dict]:
    """food_aliases rows by template_key(alias), loaded once. An empty load
    (a failed request on the server; a batch run stops instead) is tried
    again after _FOOD_ALIASES_RETRY_SECONDS, not on every line."""
    global _FOOD_ALIASES_TRIED_AT
    now = time.time()
    if not _FOOD_ALIASES and (_FOOD_ALIASES_TRIED_AT is None
                              or now - _FOOD_ALIASES_TRIED_AT > _FOOD_ALIASES_RETRY_SECONDS):
        _FOOD_ALIASES_TRIED_AT = now
        for row in load_food_aliases():
            if row.get("food") and row.get("alias"):
                _FOOD_ALIASES[tref.template_key(row["alias"])] = row
    return _FOOD_ALIASES


def _alias_match(ingredient: str, size_hint: str, unit: str) -> tuple[dict, dict | None] | None:
    """
    The food a food_aliases name stands for ("cooked penne" -> Pasta, cooked,
    enriched), and its portion when the recipe's unit is the alias's: "1 cup
    cooked penne" is "cup penne" (107 g), "1 baguette" is "1 baguette
    (about 22\" long)". Another unit ("2 slice baguette") keeps the food and
    leaves the portion to pick_best_portion, as does an alias with no portion
    (a synonym: "hot sauce" -> Hot pepper sauce). The size hint can name its
    own alias ("mini baguette"). None when no alias names the ingredient.
    """
    aliases = _food_aliases()
    row = aliases.get(tref.template_key(f"{size_hint} {ingredient}")) if size_hint else None
    row = row or aliases.get(tref.template_key(ingredient))
    if row is None:
        return None
    branded = str(row["food"].get("source_set") or "").lower() == "branded"
    food = _fetch_food_by_fdc_id(f"{'B_' if branded else ''}{row['food']['fdc_id']}")
    if food is None:
        return None
    u = unit.strip().lower()
    unit_fits = (u in ("cup", "cups") if row.get("unit") == "cup"
                 else u in ("", "piece", "pieces", "whole"))
    portion = None
    if unit_fits and row.get("portion"):
        label = _portion_label(row["portion"])
        grams = float(row["portion"].get("grams") or 0)
        portion = next((p for p in food["portions"]
                        if p["label"] == label and abs(p["gram_weight"] - grams) < 1e-6), None)
    return food, portion


def _search_usda_for_ingredient(query: str) -> USDAIndex:
    """Build a small USDAIndex from per-ingredient Supabase search (non-branded)."""
    return _search_and_build_index(query, source_set="usda")


def load_boosts(path):
    rules = list(BUILTIN_BOOSTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rules.extend(json.load(f))
    return rules


BOOST_NEUTRAL_PREFIXES = {
    "raw", "fresh", "plain", "whole", "natural", "cooked", "steamed",
    "boiled", "dried", "ground", "chopped",
    "sliced", "minced", "grated", "crushed", "peeled", "julienned",
    "shredded", "red", "green", "white", "black", "brown", "yellow",
    "short", "long", "medium", "small", "large", "baby",
}


# Words after a one-word trigger that leave it the food: its parts and the
# ways it is counted ("garlic clove", "basil leaves", "salt, kosher").
BOOST_NEUTRAL_SUFFIXES = {
    "raw", "fresh", "whole", "leaf", "leaves", "clove", "cloves", "sprig",
    "sprigs", "stalk", "stalks", "stem", "stems", "root", "piece", "pieces",
    "bulb", "head", "kosher", "sea", "flake", "flakes", "fillet", "fillets",
}


def _boost_match_is_too_generic(ingredient: str, trigger: str, rule: dict | None = None) -> bool:
    """
    Block short generic boost triggers from hijacking more specific phrases.
    This keeps matches like "pickled red ginger" from collapsing to a plain
    ginger root entry while still allowing neutral prep variants such as
    "ground ginger" or "plain rice".
    """
    ing_tokens = [_canonical_token(t) for t in normalise(ingredient).split()]
    trig_tokens = [_canonical_token(t) for t in normalise(trigger).split()]
    if len(trig_tokens) != 1 or len(ing_tokens) <= 1:
        return False
    token = trig_tokens[0]
    if token not in ing_tokens:
        return False
    idx = ing_tokens.index(token)
    prefixes = ing_tokens[:idx]
    if any(tok not in BOOST_NEUTRAL_PREFIXES and tok not in PREP_WORDS for tok in prefixes):
        return True
    # A word after it that the rule's food doesn't have names a food the
    # trigger only describes: "potato gnocchi" is gnocchi, and the "potato"
    # rule made it raw potato, though USDA "Gnocchi, potato" scored 1.675;
    # "garlic fried rice" was garlic (22 Oct 2026). "kabocha squash" keeps
    # its rule: the pinned "Squash, winter" has the word.
    raw_tokens = normalise(ingredient).split()
    suffixes = [tok for tok, raw in zip(ing_tokens[idx + 1:], raw_tokens[idx + 1:])
                if raw not in BOOST_NEUTRAL_SUFFIXES and raw not in PREP_WORDS]
    if not suffixes or rule is None:
        return False
    named = normalise(rule.get("boost", ""))
    if rule.get("fdc_id"):
        try:
            pinned = _fetch_food_by_fdc_id(str(rule["fdc_id"]))
        except Exception:
            return False  # can't tell; keep the rule
        if pinned is None:
            return False
        named += " " + normalise(f"{pinned['display_name']} {pinned.get('raw_description', '')}")
    named_tokens = {_canonical_token(t) for t in named.split()}
    return any(tok not in named_tokens for tok in suffixes)


def _boost_trigger_matches(ingredient: str, trigger: str, exact: bool = False) -> bool:
    """
    Match a boost trigger against an ingredient name.

    Keep the fast substring check for ordinary phrases, but also treat
    reordered descriptor pairs as equivalent so rules like "silken tofu"
    and ingredient text like "tofu, silken" resolve through the same map.
    With exact=True the whole ingredient must be the trigger, so a
    one-word rule like "oil" can't fire inside "boiled" or "tuna in oil".
    """
    ing_norm = normalise(ingredient)
    trig_norm = normalise(trigger)
    if not ing_norm or not trig_norm:
        return False
    if exact:
        return ing_norm == trig_norm
    # Whole words (a plural too): "egg" isn't in "eggplant", "salt" in
    # "unsalted", "ginger" in "gingerbread", "butter" in "buttermilk".
    if re.search(rf"(?<![a-z0-9]){re.escape(trig_norm)}(?:e?s)?(?![a-z0-9])", ing_norm):
        return True

    ing_tokens = [_canonical_token(t) for t in ing_norm.split() if t]
    trig_tokens = [_canonical_token(t) for t in trig_norm.split() if t]
    if len(trig_tokens) <= 1 or len(ing_tokens) != len(trig_tokens):
        return False
    # Reordered only ("tofu, silken"): a plural alone doesn't wake a rule
    # written for the other spelling ("gyoza wrappers" at 9 g each).
    return ing_tokens != trig_tokens and sorted(ing_tokens) == sorted(trig_tokens)


def _boost_changes_colour(ingredient: str, rule: dict) -> bool:
    """A rule whose search names another colour than the line: "bell
    pepper" searches "sweet red pepper", and "yellow bell pepper" came out
    red (22 Oct 2026). apply_boosts swaps in the line's colour."""
    said = set(normalise(ingredient).split()) & COLOR_WORDS
    boost = set(normalise(rule.get("boost", "")).split()) & COLOR_WORDS
    return bool(said and boost and not said & boost)


def apply_boosts(ingredient, boost_rules, category=""):
    """
    Apply the first matching boost rule to ingredient.

    Rule fields:
      trigger              : substring to match in ingredient name (required)
      boost                : alternative search string (required unless portion_gram_weight)
      weight               : confidence bonus 0-1 (default 0.6)
      category             : only fire when recipe category contains this string (optional)
      exact                : true = fire only when the whole ingredient is the trigger (optional)
      portion_gram_weight  : synthesize a portion with this gram weight
      portion_label        : label for the synthesized portion (e.g. "1 tbsp")

    Returns (boosted_text, weight, pinned_fdc_id).
    Portion override rules are handled separately by get_portion_override().
    """
    ing = ingredient.lower()
    cat = category.lower()
    for rule in boost_rules:
        if rule.get("_disabled"):
            continue
        if "trigger" not in rule:
            continue   # skip comment/metadata objects
        if not _boost_trigger_matches(ingredient, rule["trigger"], rule.get("exact", False)):
            continue
        if _boost_match_is_too_generic(ingredient, rule["trigger"], rule):
            continue
        if _boost_changes_colour(ingredient, rule) and not rule.get("fdc_id"):
            # The line's colour in the rule's search: "yellow bell pepper"
            # searches "sweet yellow pepper raw", not red.
            said = [t for t in normalise(ingredient).split() if t in COLOR_WORDS]
            rule = {**rule, "boost": " ".join(
                said[0] if t in COLOR_WORDS else t for t in normalise(rule["boost"]).split())}
        if any(ex.lower() in ing for ex in rule.get("exclude", [])):
            continue
        rule_cat = rule.get("category", "").lower()
        if rule_cat and rule_cat not in cat:
            continue
        # Portion override rules don't affect the search string
        if "portion_gram_weight" in rule and "boost" not in rule:
            continue
        if rule.get("fdc_id"):
            # Use the boost text as search query if provided, so the pinned
            # FDC ID appears in the search results even when the trigger
            # text wouldn't find it (e.g. "spring onion" → search "green onion"
            # to find fdc_id 170005).
            search_text = rule.get("boost", ingredient)
            return search_text, 0.0, rule["fdc_id"]
        return rule["boost"], rule.get("weight", 0.6), None
    return ingredient, 0.0, None

def get_portion_override(ingredient: str, boost_rules: list, unit: str = "",
                         unit_rules_only: bool = False) -> dict | None:
    """
    Return a synthesized portion dict if a portion_gram_weight rule matches
    this ingredient, otherwise None.

    Used in pick_best_portion to handle foods with no serving size where
    the recipe uses a volumetric unit (tbsp, tsp, cup, etc.).

    Rule schema:
      {"trigger": "mirin", "portion_gram_weight": 13.5, "portion_label": "1 tbsp"}

    Optional: "portion_unit" field restricts the rule to a specific recipe unit.
      {"trigger": "panko", "portion_unit": "tbsp", "portion_gram_weight": 6, "portion_label": "1 tbsp"}
    """
    COUNTABLE_OVERRIDE_UNITS = {
        "piece", "pieces",
        "block", "blocks",
        "wrapper", "wrappers",
        "sheet", "sheets",
        "fillet", "fillets",
        "steak", "steaks",
        "patty", "patties",
        "chop", "chops",
        "drumstick", "drumsticks",
        "knob", "knobs",
        "cube", "cubes",
        "stick", "sticks",
        "whole",
        "ear", "ears",
        "head", "heads",
        "slice", "slices",
        "serving", "servings",
        "clove", "cloves",
        "bunch", "bunches",
        "unit", "units",
        "item", "items",
    }

    ing = ingredient.lower()
    u = unit.lower().strip()
    # Normalise common unit aliases for matching
    u_norm = u
    if u in ("tablespoon", "tablespoons"): u_norm = "tbsp"
    if u in ("teaspoon", "teaspoons"):     u_norm = "tsp"
    if u in ("cups",):                     u_norm = "cup"

    best = None
    for rule in boost_rules:
        if "portion_gram_weight" not in rule:
            continue
        if "trigger" not in rule:
            continue
        if not _boost_trigger_matches(ingredient, rule["trigger"], rule.get("exact", False)):
            continue
        if any(ex.lower() in ing for ex in rule.get("exclude", [])):
            continue
        rule_unit = rule.get("portion_unit", "").lower().strip()
        if unit_rules_only and not rule_unit:
            continue
        if rule_unit and rule_unit != u_norm:
            if not (
                rule_unit in COUNTABLE_OVERRIDE_UNITS
                and (u_norm in COUNTABLE_OVERRIDE_UNITS or not u_norm)
            ):
                continue   # unit-specific rule â€” skip if unit doesn't match
        gw = float(rule["portion_gram_weight"])
        result = {
            "portion_id":  f"override_{rule['trigger'].replace(' ','_')}",
            "label":       rule.get("portion_label", f"{gw:.0f}g"),
            "gram_weight": gw,
            "gram_col":    "override",
            "portion_idx": 1,
        }
        # Prefer unit-specific match over generic match
        if rule_unit:
            if rule_unit != u_norm and not (
                rule_unit in COUNTABLE_OVERRIDE_UNITS
                and (u_norm in COUNTABLE_OVERRIDE_UNITS or not u_norm)
            ):
                continue
            return result
        if best is None:
            best = result
    return best


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Matching
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_WEIGHT_UNITS = {"g", "gram", "grams", "kg", "oz", "ounce", "ounces", "lb", "lbs",
                 "pound", "pounds", "ml", "l"}


_BASIS_LABEL_RE = re.compile(r"^\s*(?:100\s*(?:g|grm|grams?)\b.*)?$", re.I)


def _is_basis_portion(p: dict) -> bool:
    """
    The per-100 g basis row ("100g", portion_idx 0), not a real measure that
    happens to weigh about 100 g. Every 100 g portion used to be skipped, so
    FNDDS "Green beans, raw" (1 cup = 100 g) had no cup, and "1 cup green
    beans" swapped to "Green beans, pickled" for its 145 g cup (22 Oct 2026).
    """
    if p.get("portion_idx", 1) == 0:
        return True
    return (abs(p.get("gram_weight", 100.0) - 100.0) <= 1.0
            and bool(_BASIS_LABEL_RE.match(p.get("label") or "")))


def _has_unit_portion(food: dict, unit: str) -> bool | None:
    """
    Whether *food* has a portion that can express the recipe *unit*.
    None when the unit doesn't depend on portions (weights convert via grams).
    """
    u = (unit or "").lower().strip()
    if u in _WEIGHT_UNITS:
        return None
    if u in VOLUMETRIC_UNITS:
        return _has_compatible_volumetric_serving(food, u)
    keywords = PORTION_UNIT_KEYWORDS.get(u) or (
        PORTION_UNIT_KEYWORDS["piece"] if u in ("", "pieces") else None)
    if not keywords:
        return None
    for p in food.get("portions", []):
        if _is_basis_portion(p):
            continue
        label = p.get("label", "").lower()
        if any(re.search(rf"\b{re.escape(kw)}", label) for kw in keywords):
            return True
    return False


# The word lists shared with the app's food search (search_rules.json, a
# copy of blobb-app's lib/data/search_rules.json; food_name_search ranks with
# them). The recipe layer reads its cooking words and skin rule.
SEARCH_RULES = json.loads(Path(__file__).with_name("search_rules.json").read_text())


# A preparation the line names that makes a different food: "mashed
# potatoes", "fried rice", "hard boiled egg". A boost's pinned food stands
# aside when it doesn't name it, and the line is searched like any other:
# the potato pin took "mashed potatoes" to raw potatoes (23 Oct 2026).
PRODUCT_PREP_WORDS = set(SEARCH_RULES["cooking_words"]["words"]) | {
    "mashed", "fried", "scrambled", "deviled"}


def _line_preparations(ingredient: str) -> set[str]:
    """Preparations named before the food, not after a comma: "eggs,
    scrambled" is raw eggs to scramble."""
    return {w for w in normalise(ingredient.split(",")[0]).split() if w in PRODUCT_PREP_WORDS}


def _fits_preparations(food: dict | None, preparations: set[str]) -> bool:
    """Whether *food* is what the line's preparations make: it names each one,
    or, for a plain cooking word ("grilled", "roasted"), is cooked at all;
    "grilled chicken" is the generic cooked chicken. "mashed", "fried",
    "scrambled" and "deviled" make a different food and must be named."""
    if food is None or not preparations:
        return True
    named = set(normalise(f"{food.get('display_name', '')} {food.get('raw_description', '')}").split())
    cooked = any(COOKING_WORD_RE.fullmatch(w) for w in named)
    return all(w in named or (cooked and COOKING_WORD_RE.fullmatch(w)) for w in preparations)


# Cooking words are variants too, in recipes only: a recipe's food is raw
# ("Turkey, Ground, cooked" isn't "ground turkey", "1 cup quinoa" is
# uncooked), unless the line is cooked or names a way of cooking it ("baked
# beans"). The app's search leaves them out (search_rules.json).
COOKING_WORD_RE = re.compile(r"\b(" + "|".join(SEARCH_RULES["cooking_words"]["words"]) + r")\b")

# Chicken breast means skinless unless the line mentions skin: a skin-on row
# is one more variant.
SKINLESS_BY_DEFAULT_CUTS = set(SEARCH_RULES["skin"]["skinless_by_default_cuts"])
SKIN_ON_RE = re.compile(r"\b(" + SEARCH_RULES["skin"]["skin_on_pattern"] + r")\b")


# USDA rows that are someone's finished dish, not an ingredient: "Mozzarella
# sticks, Applebee's" tied "fresh mozzarella" at 0.69 and won on search order
# over "Mozzarella cheese, whole milk"; "Pepperoni pizza, 14\"" outscored
# "Pepperoni, beef and pork, sliced" for "pepperoni" (22 Oct 2026). They are
# left out unless the line names the dish: every word of the row's name
# before its first comma ("pepperoni pizza").
DISH_ONLY_CATEGORIES = {"restaurant foods", "fast foods"}
# Pure fat is about 900 kcal per 100 g. "JAPANESE STYLE MAYONNAISE" (branded
# 2278440) says 2000, and won "Japanese mayonnaise" (22 Oct 2026).
MAX_KCAL_PER_100G = 905.0
# Categories of prepared dishes, which lose ties to plain foods.
DISH_CATEGORY_RE = re.compile(
    r"restaurant|fast food|meals|entrees|side dishes|mixed dishes|pizza|"
    r"sandwich|burger|soups?\b|baby food|muffins|quick breads|cakes|pies|"
    r"cookies|brownies|pastries|doughnuts|desserts",
    re.IGNORECASE,
)


# Tie-break order of USDA datasets: the standard reference rows first.
DATA_TYPE_RANK = {"foundation": 3, "sr legacy": 3, "survey (fndds)": 2}


def _is_unasked_dish(food: dict, query_tokens: set[str]) -> bool:
    if food.get("source") != "usda":
        return False
    if (food.get("category") or "").strip().lower() not in DISH_ONLY_CATEGORIES:
        return False
    head = (food.get("display_name") or "").split(",")[0]
    head_tokens = {_canonical_token(t) for t in normalise(head).split()}
    return not head_tokens or not head_tokens <= query_tokens


# Foods of one community, named for it: "Yellow cornmeal (Navajo)" took
# "yellow cornmeal" from "Cornmeal, whole-grain, yellow" (22 Oct 2026).
# Ranked behind unless the line names it.
SPECIALTY_CATEGORIES = {"american indian/alaska native foods"}


def _is_specialty_row(food: dict, query_tokens: set[str]) -> bool:
    if (food.get("category") or "").strip().lower() not in SPECIALTY_CATEGORIES:
        return False
    named = re.findall(r"\(([^)]*)\)", f"{food.get('display_name', '')} {food.get('raw_description', '')}")
    named_tokens = {_canonical_token(t) for n in named for t in normalise(n).split()}
    return not named_tokens & query_tokens


def _is_dish_category(food: dict) -> bool:
    return bool(DISH_CATEGORY_RE.search(food.get("category") or ""))


def _data_type_rank(food: dict) -> int:
    rank = DATA_TYPE_RANK.get((food.get("data_type") or "").strip().lower(), 1)
    # A Foundation row without calories is a data gap, not a reference row.
    if (food.get("data_type") or "").lower() == "foundation" and not food.get("energy_kcal"):
        return 0
    return rank


def _has_measurable_portion(food: dict) -> bool:
    """A portion people can measure with: not USDA's "RACC" or a bare 100 g."""
    for p in food.get("portions", []):
        label = (p.get("label") or "").strip().lower()
        if label and "racc" not in label and not _is_basis_portion(p):
            return True
    return False


_SERVING_VOLUME_RE = re.compile(r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|ml|fl)\b", re.I)
_SERVING_WEIGHT_RE = re.compile(r"\b(onz|oz|ounces?|lbs?|pounds?|g|grm|grams?|kg)\b", re.I)


def _serving_kind(food: dict) -> str:
    """A branded label's serving ("2 ONZ", "1 1/4 cup", "1 bar") as "weight",
    "volume" or "count", the kinds _unit_kind gives recipe units."""
    text = str(food.get("serving_text") or "")
    if _SERVING_VOLUME_RE.search(text):
        return "volume"
    return "weight" if _SERVING_WEIGHT_RE.search(text) else "count"


def _typical_branded(group: list[dict], unit: str) -> dict:
    """
    One of several branded products with the same name and score: the one
    whose label serving is in the recipe's kind of unit, then the most common
    serving size among those, then the closest to their median calories.
    Twelve products are named "LINGUINE": nine dry pastas labelled per 2 oz
    (56 g, 333-375 kcal), two fresh deli pastas per 1 1/4 cup (85 g, 282-306)
    and a dinner kit. The first one fetched used to win, a fresh one
    (22 Oct 2026).
    """
    kind = (_unit_kind(unit) or (None, "count"))[1]
    fit = [f for f in group if _serving_kind(f) == kind] or group
    def serving(f):
        try:
            return round(float(f.get("serving_grams") or 0))
        except (TypeError, ValueError):
            return 0
    counts = Counter(serving(f) for f in fit)
    common = max(sorted(counts), key=lambda s: counts[s])
    typical = [f for f in fit if serving(f) == common]
    median = statistics.median_low([f.get("energy_kcal") or 0.0 for f in typical])
    return min(typical, key=lambda f: (abs((f.get("energy_kcal") or 0.0) - median), str(f["fdc_id"])))


def _best_volumetric_portion(portions: list[dict], unit: str) -> dict | None:
    """
    Find the best real serving portion for any volumetric recipe unit.
    Prefers an exact unit match, then any convertible volumetric portion.
    """
    recipe_unit = _normalise_volume_unit(unit)
    if not recipe_unit or recipe_unit not in VOLUME_TO_TSP:
        return None

    recipe_qty_tsp = VOLUME_TO_TSP[recipe_unit]
    best_exact = None
    best_convertible = None
    best_exact_diff = None
    best_convertible_diff = None

    for p in portions:
        if _is_basis_portion(p):
            continue
        label_unit = _portion_label_unit(p["label"])
        if not label_unit or label_unit not in VOLUME_TO_TSP:
            continue
        label_qty, label_qty_unit = _portion_label_volume_qty(p["label"])
        label_qty_tsp = label_qty * VOLUME_TO_TSP[label_qty_unit]
        diff = abs(label_qty_tsp - recipe_qty_tsp)
        if label_qty_unit == recipe_unit:
            if best_exact is None or diff < best_exact_diff:
                best_exact = p
                best_exact_diff = diff
        else:
            if best_convertible is None or diff < best_convertible_diff:
                best_convertible = p
                best_convertible_diff = diff

    return best_exact or best_convertible


# Ingredients containing these trigger strings get remapped to a cleaner
# search term before matching. Applied after boost rules.
INGREDIENT_REMAP = {
    # Not "black pepper ground": the matcher drops "ground" anyway, and the
    # shared search found a branded "BLACK PEPPER GROUND" over "Spices,
    # pepper, black" (26 Oct 2026).
    "peppercorn":        "black pepper",
    "peppercorns":       "black pepper",
    "whole pepper":      "black pepper",
    "rice wine vinegar": "rice vinegar",
    "soybean powder":     "soy flour",
    "soy bean powder":    "soy flour",
    "instant yeast":      "yeast",
    "taro root":          "taro",
    "banana heart":       "banana blossom",
    "salted egg":         "salted duck egg",
    "nata de coco":       "coconut gel",
    # Cooked rice variants â†’ White rice, long-grain, cooked (FDC 168878 cooked)
    # These are only reached when the recipe explicitly says "cooked" â€” the
    # is_cooked flag in build_output_rows suppresses the yield factor so grams
    # aren't double-deflated.
    "cooked rice":        "white rice long grain cooked",
    "steamed rice":       "white rice long grain cooked",
    "boiled rice":        "white rice long grain cooked",
    "plain rice":         "white rice long grain cooked",
    "cooked white rice":  "white rice long grain cooked",
    "cooked jasmine rice":"white rice long grain cooked",
    "cooked basmati rice":"white rice long grain cooked",
    "day-old rice":       "white rice long grain cooked",
    "leftover rice":      "white rice long grain cooked",
    "shimeji mushroom":   "beech mushroom",
    # USDA's skim milk is "Milk, nonfat, ..." or "Milk, fat free (skim)";
    # "skim milk" found "Yogurt, plain, skim milk" (23 Oct 2026).
    "skim milk":          "nonfat milk",
    "fat free milk":      "nonfat milk",
    "fat-free milk":      "nonfat milk",
    # NOTE: bare "white rice", "jasmine rice", "basmati rice", "long grain rice"
    # are intentionally NOT remapped here â€” they are uncooked and handled by
    # boost rules pointing to the raw USDA entry (FDC 168878 raw).
}

# Chicken cuts a line can name: the cut keeps its skin unless the line says
# skinless, breast is skinless unless it says skin (_chicken_cut).
CHICKEN_CUTS = ("thigh", "drumstick", "breast", "wing")
CHICKEN_CUT_SKINLESS_TRIGGERS = {"skinless", "skin removed", "skin-off", "skin off", "no skin"}
# Recipes that say "chicken breast" nearly always mean boneless, skinless;
# these cuts take skin only when the recipe asks for it.
CHICKEN_CUT_SKINLESS_BY_DEFAULT = {"breast"}
CHICKEN_CUT_SKIN_ON_TRIGGERS = {"skin-on", "skin on", "with skin", "bone-in", "bone in"}
CHICKEN_CUT_EXCLUDES = {
    "ground", "mince", "minced", "broth", "stock", "sausage",
    "nugget", "tender", "strips", "cutlet",
}


# Raw-to-cooked yield of a meat matched to a cooked food, so a raw recipe
# weight counts the cooked food's calories right (USDA Agriculture Handbook
# No. 102 cooking yield tables).
MEAT_YIELDS = {"pork": 0.73, "beef": 0.70, "lamb": 0.70, "veal": 0.74}


# Meat sold raw by weight: with MEAT_YIELDS' words, the line's meat is raw
# ("2 lb oxtail", "1.5 lb pork shoulder"), so a raw row comes first.
RAW_MEAT_WORDS = set(MEAT_YIELDS) | {"chicken", "turkey", "duck", "goat", "oxtail", "oxtails"}
# USDA's own raw-to-cooked weight for a food listed cooked ("1 oz yields",
# 16 g of cooked oxtail meat, bone out, from 1 oz raw as bought).
OZ_YIELDS_RE = re.compile(r"^\s*1\s+oz\s+yields\b", re.I)


def _row_words_text(row: dict) -> str:
    return f"{row.get('description') or ''} {row.get('display_name') or ''}".lower()


def _is_raw_meat_weight_line(ingredient: str, unit: str, line_cooked: bool) -> bool:
    return (not line_cooked and _normalise_weight_unit(unit) is not None
            and bool(RAW_MEAT_WORDS & set(normalise(ingredient).split())))


def _cooked_meat_yield(food: dict, meat_kw: str | None) -> float | None:
    """
    The weight a raw recipe amount has as *food*, when *food* is the meat
    cooked: USDA's own "1 oz yields" portion (oxtail: 16 g, 0.56, bone and
    cooking loss), else MEAT_YIELDS for the meat. None when *food* isn't
    cooked: a raw row, or a branded product, whose label is as sold (pork
    tocino was 0.73 of its raw weight, 27 Oct 2026). Cooked by its words,
    not is_raw: "Pork, fresh, shoulder, ..., cooked, braised" says "fresh",
    which is_raw reads as raw (28 Oct 2026).
    """
    if food.get("source") != "usda":
        return None
    text = f"{food.get('raw_description') or ''} {food.get('display_name') or ''}".lower()
    fndds = "fndds" in str(food.get("data_type") or "").lower()
    if not (COOKING_WORD_RE.search(text) or (fndds and not food.get("is_raw"))):
        return None
    for p in food.get("portions", []):
        if OZ_YIELDS_RE.match(p.get("label") or "") and p.get("gram_weight"):
            return p["gram_weight"] / WEIGHT_TO_G["oz"]
    return MEAT_YIELDS.get(meat_kw) if meat_kw else None


def _meat_keyword(ingredient: str) -> str | None:
    """Return the first meat keyword in the ingredient name, as a word
    ("beefsteak tomato" names no beef), or None."""
    ing = ingredient.lower()
    for kw in MEAT_YIELDS:
        if re.search(rf"\b{kw}\b", ing):
            return kw
    return None

# Pasta types that are given raw in recipes but matched to cooked DB entries.
# Yield factor 2.0 â€” dry pasta roughly doubles in weight when cooked.
PASTA_KEYWORDS = {
    "lasagne","lasagna","shell","farfalle","spaghetti","elbow","rotini",
    "penne","fettuccine","fettuccini","linguine","linguini","rigatoni",
    "tagliatelle","pappardelle","fusilli","orecchiette","cavatappi",
    "macaroni","macaroni","vermicelli","angel hair","capellini","ziti",
    "conchiglie","gemelli","campanelle","ditalini","orzo","pasta",
    "bucatini","acini di pepe",
}
PASTA_YIELD_FACTOR = 2.0
# Cooked pasta from dry (RECIPE_RULES, "Cooked starches"): a cup is about
# 2 oz dry, and cooked weight is about 2.35 x dry.
DRY_PASTA_OZ_PER_COOKED_CUP = 2.0
DRY_PASTA_COOKED_WEIGHT_RATIO = 2.35
# Below this a branded pasta isn't the dry product.
DRY_PASTA_MIN_KCAL = 300.0


def _is_cooked_food(food: dict) -> bool:
    return bool(re.search(r"\bcooked\b", f"{food.get('raw_description', '')} "
                                         f"{food.get('display_name', '')}".lower()))

def _pasta_keyword(ingredient: str) -> bool:
    """Return True if the ingredient name contains a pasta keyword."""
    ing = ingredient.lower()
    if any(ex in ing for ex in ("sauce","soup","salad","paste")):
        return False
    return any(kw in ing for kw in PASTA_KEYWORDS)

# Rice: uncooked dry rice is the default assumption (recipe says nothing).
# USDA raw entry (FDC 168878) is per 100g dry â€” no yield adjustment needed
# when matching to raw entry.
# "cooked rice" variants remap to the cooked entry and is_cooked suppresses
# any yield factor so grams are not deflated a second time.
RICE_EXCLUDES = {"flour", "wine", "vinegar", "paper", "noodle", "cake",
                 "syrup", "pudding", "crispy", "puffed", "porridge", "congee",
                 "koji"}

def _rice_keyword(ingredient: str) -> bool:
    """Return True if ingredient is plain rice (not a rice-derived product)."""
    ing = ingredient.lower()
    return "rice" in ing and not any(ex in ing for ex in RICE_EXCLUDES)

CUBE_KEYWORDS = ["cube", "cubes"]


def _as_row(food: dict) -> dict:
    """A built USDA food as layer 1 reads a foods row."""
    return {"description": food.get("raw_description") or food.get("display_name") or "",
            "display_name": food.get("display_name") or "",
            "source_set": (food.get("data_type") or "").lower().replace(" ", "_"),
            "data_type": food.get("data_type") or "",
            "calories_100g": food.get("energy_kcal")}


def _layer1_rank(search: str, food: dict) -> tuple:
    return food_name_search.score_row(food_name_search.Query.parse(search), _as_row(food)).key()


def _names_other_variant(search: str, food: dict) -> bool:
    """A USDA row naming a variant *search* doesn't (layer 1's variant
    words), or cooked: never one to borrow a volume from ("Lite" syrup)."""
    query = food_name_search.Query.parse(search)
    return bool(food_name_search.usda_variant_count(query, food.get("raw_description") or "")
                or _recipe_variant_delta(query, _as_row(food), False, None) > 0)


def _volume_unit_fallback(food, foods, unit, search, query_tokens):
    """
    For a cup/tbsp/tsp recipe amount, a food with no volume portion can't be
    measured: "1.5 cups" became 1.5 × its "RACC" serving (flour: 45 g, not
    190 g). The food stays; its volume comes from a sibling's: a candidate
    with a plain volume portion whose name carries every ingredient word
    ("all-purpose" + "flour", so not rice flour), the one sharing the most
    description words with *food*, then the best layer-1 rank. That portion is
    added to a copy of *food* ("_density_from" names the sibling).

    It used to return the sibling itself, a different food: "green beans"
    became "Green beans, pickled" and "heavy cream" (Foundation, 1 RACC
    only) "Heavy whipping cream" (22 Oct 2026). Now only the same food is
    returned (_same_usda_food): Foundation all-purpose flour (1 RACC) is
    SR Legacy's, with its "1 cup" (Arianna, 27 Oct 2026). A volume line
    takes another food's cup as a density only. Keeps *food* unchanged
    when no candidate qualifies.
    """
    # ml already converts to grams (1 ml ≈ 1 g), so only spoons and cups
    # depend on the food having a volume portion; counts ("1 medium", "2
    # stalks") on a count portion. Weights convert by grams.
    if unit.lower() in VOLUMETRIC_UNITS:
        if to_grams(1.0, unit, "") is not None or _has_compatible_volumetric_serving(food, unit):
            return food
    elif _has_unit_portion(food, unit) is not False or _own_count_portion(food, search):
        return food
    # The same food in another USDA dataset, with the portion: match it.
    if unit.lower() in VOLUMETRIC_UNITS:
        same = [c for c in foods if c is not food and _same_usda_food(food, c)
                and not _names_other_variant(search, c) and _density_portion(c, unit, search)]
        if same:
            return {**max(same, key=lambda c: _layer1_rank(search, c)), "_same_food_as": food["fdc_id"]}
    food_tokens = set(normalise(food.get("raw_description") or food["display_name"]).split())
    best, best_key, best_portion = None, None, None
    for cand in foods:
        if cand is food or not cand.get("energy_kcal"):
            continue
        portion = _density_portion(cand, unit, search)
        if portion is None:
            continue
        if _names_other_variant(search, cand) or _is_dish_category(cand):
            continue
        label_tokens = (set(normalise(cand["display_name"]).split())
                        | set(normalise(cand.get("raw_description", "")).split()))
        if not all(_token_in_label(tok, label_tokens) for tok in query_tokens):
            continue
        overlap = len(food_tokens & set(normalise(cand.get("raw_description") or cand["display_name"]).split()))
        key = (overlap, _layer1_rank(search, cand))
        if best is None or key > best_key:
            best, best_key, best_portion = cand, key, portion
    if best is None:
        best, best_portion = _density_relative(food, foods, unit, search, query_tokens)
    if best is None and unit.lower() in VOLUMETRIC_UNITS:
        best, best_portion = _density_from_head_food(food, unit, search)
    if best is None:
        return food
    # A volume line keeps the food's own servings (Arianna, 27 Oct 2026):
    # the borrowed cup only says how many grams the line is
    # (_own_serving_for_volume), it is never shown as the food's portion.
    if unit.lower() in VOLUMETRIC_UNITS:
        qty, label_unit = _portion_label_volume_qty(best_portion["label"])
        ml = _volume_to_ml(qty, label_unit or _portion_label_unit(best_portion["label"]) or "")
        if not ml:
            return food
        return {**food, "_g_per_ml": best_portion["gram_weight"] / ml,
                "_density_from": best["fdc_id"]}
    borrowed = {**best_portion,
                "portion_id": f"{food['fdc_id']}-vol-{best['fdc_id']}",
                "portion_idx": max([p.get("portion_idx", 0) for p in food.get("portions", [])] + [0]) + 1}
    return {**food, "portions": list(food.get("portions", [])) + [borrowed],
            "_density_from": best["fdc_id"]}


# How far apart two rows of the same food's calories may be: USDA's
# datasets differ by method (Atwater factors, sampling), not by food.
SAME_FOOD_KCAL_TOLERANCE = 0.2


def _same_usda_food(food: dict, cand: dict) -> bool:
    """Whether *cand* is *food* in another USDA dataset: a USDA row whose
    words are *food*'s, give or take USDA's standard and state words
    ("Wheat flour, white, all-purpose, enriched, bleached" for Foundation
    "Flour, wheat, all-purpose, enriched, bleached"; "Nuts, almonds" for
    almonds), with about the same calories. Not "Green beans, pickled" for
    green beans."""
    if cand.get("source") != "usda" or food.get("source") not in ("usda", None):
        return False
    a, b = food.get("energy_kcal") or 0, cand.get("energy_kcal") or 0
    if not a or not b or abs(a - b) / max(a, b) > SAME_FOOD_KCAL_TOLERANCE:
        return False
    def words(f):
        # A leading USDA group label isn't a word about the food: "Nuts,
        # almonds" is almonds.
        segs = (f.get("raw_description") or "").split(",")
        if len(segs) > 1 and normalise(segs[0]) in food_name_search.GROUP_LABELS:
            segs = segs[1:]
        text = f"{','.join(segs)} {f.get('display_name') or ''}"
        return {_canonical_token(w) for w in normalise(text).split()
                if w not in food_name_search.STANDARD_WORDS and w not in food_name_search.STATE_WORDS}
    return words(cand) <= words(food)


def _mismatch_amount(qty: float, unit: str, portion: dict,
                     g_per_ml: float | None = None) -> tuple[float, bool]:
    """How many [portion]s a volume line is when the portion isn't a
    volume: its grams at [g_per_ml] (a relative's cup, _volume_unit_fallback)
    or 1 g/ml, never [qty] of them ("1 tsp sweetened plantain" was 1 whole
    plantain, 220 kcal, 27 Oct 2026). (qty, False) when the line isn't a
    volume either."""
    ml = _volume_to_ml(qty, unit)
    if ml is None or not portion.get("gram_weight"):
        return qty, False
    return ml * (g_per_ml or 1.0) / portion["gram_weight"], True


def _own_serving_for_volume(food: dict) -> dict | None:
    """
    For a cup or spoon line on a food with no volume portion, the serving
    it does have (Arianna, 27 Oct 2026): a count or household one first
    ("1 olive", "1 serving", "1 medium"; a package last), then a weight
    ("1 oz"). Never a
    made-up "1 tbsp", a relative's cup, the 100 g basis or a RACC. None
    when it has nothing else: the line is then in grams.
    """
    own = [p for p in food.get("portions", [])
           if p.get("gram_weight") and not _is_basis_portion(p)
           and not UNMEASURABLE_PORTION_RE.search(p.get("label") or "")
           and not re.search(r"-(?:vol|est)-", str(p.get("portion_id", "")))]
    # A package ("1 container") after a serving of the food itself.
    counted = sorted((p for p in own if not WEIGHT_PORTION_LABEL_RE.match(p.get("label") or "")),
                     key=lambda p: _is_package_label(p.get("label") or ""))
    return (counted or own or [None])[0]


# How far a head-food relative may differ from the food in calories, and
# its rows from each other in grams per ml, to lend its cup: dry pasta's
# cups by shape differ 1.9x (USDA, 27 Oct 2026), raw potatoes' 1.0x.
HEAD_BORROW_SPREAD = 1.5


def _food_head_word(food: dict) -> str:
    """The food a name is of: the last word of its first part ("YUKON GOLD
    POTATOES" potatoes, "ACINI DI PEPE PASTA" pasta, "Plantains, raw"
    plantains)."""
    name = food.get("raw_description") or food.get("display_name") or ""
    words = normalise(name.split(",")[0]).split()
    return words[-1] if words else ""


def _density_from_head_food(food, unit, search):
    """
    The last try for a volume: a USDA row headed by the food *food* is of
    (_food_head_word), in the same raw or cooked state, with a plain volume
    portion. "Yukon gold potato" (a branded bag, no cup) is measured by
    "Potatoes, raw" (1 cup diced, 150 g), not 1 g/ml (236 g); USDA's
    "Plantain, raw" by "Plantains, yellow, raw" (a sweetened plantain
    product, about 200 kcal to 122, is too far off). The row says little
    else: at most one word past its head and USDA's standard words ("Plantains, yellow, raw", not
    "Noodles, chow mein"), and its calories are within HEAD_BORROW_SPREAD
    of *food*'s (konjac noodles, about 10 kcal, aren't dry egg noodles,
    384). None when the rows that qualify disagree on the density by more
    than HEAD_BORROW_SPREAD: a food measured by its shape (dry pasta, 0.27
    g/ml shells to 0.52 elbows) can't borrow a cup. The calories stay
    *food*'s. Returns (row, portion) or (None, None).
    """
    head = _food_head_word(food)
    if not head:
        return None, None
    cooked = _is_cooked_food(food)
    food_tokens = set(normalise(food.get("raw_description") or food["display_name"]).split())
    best, best_key, best_portion = None, None, None
    densities = []
    for cand in _search_usda_for_ingredient(head):
        if cand["fdc_id"] == food["fdc_id"] or not cand.get("energy_kcal"):
            continue
        if _canonical_token(_food_head_word(cand)) != _canonical_token(head):
            continue
        extra = {w for w in normalise(cand.get("raw_description") or cand["display_name"]).split()
                 if _canonical_token(w) != _canonical_token(head) and w not in food_tokens
                 and w not in food_name_search.STANDARD_WORDS and w not in food_name_search.STATE_WORDS}
        if len(extra) > 1:
            continue
        if (_is_cooked_food(cand) != cooked or _is_dish_category(cand)
                or _names_other_variant(search, cand)):
            continue
        if food.get("energy_kcal") and not _within(cand["energy_kcal"], food["energy_kcal"],
                                                   HEAD_BORROW_SPREAD):
            continue
        # "1 cup, cooked" measures cooked pasta, whatever the row is named.
        for portion in _volume_portions(cand):
            if bool(re.search(r"\bcooked\b", portion["label"], re.I)) == cooked:
                densities.append(_grams_per_ml(portion))
        portion = _density_portion(cand, unit, search)
        if portion is None or bool(re.search(r"\bcooked\b", portion["label"], re.I)) != cooked:
            continue
        overlap = len(food_tokens & set(normalise(cand.get("raw_description") or cand["display_name"]).split()))
        key = (_layer1_rank(head, cand)[0] == 4, overlap, _layer1_rank(head, cand))
        if best is None or key > best_key:
            best, best_key, best_portion = cand, key, portion
    densities = [d for d in densities if d]
    if densities and not _within(max(densities), min(densities), HEAD_BORROW_SPREAD):
        return None, None
    return best, best_portion


def _within(a: float, b: float, ratio: float) -> bool:
    return a > 0 and b > 0 and max(a, b) / min(a, b) <= ratio


def _volume_portions(food: dict) -> list[dict]:
    return [p for p in food.get("portions", [])
            if p.get("gram_weight") and _portion_label_unit(p.get("label") or "") in VOLUME_TO_TSP]


def _grams_per_ml(portion: dict) -> float | None:
    qty, unit = _portion_label_volume_qty(portion["label"])
    ml = _volume_to_ml(qty, unit or _portion_label_unit(portion["label"]) or "")
    return portion["gram_weight"] / ml if ml else None


def _density_relative(food, foods, unit, search, query_tokens):
    """
    When no candidate carries every ingredient word: a USDA reference row
    (Foundation, SR Legacy) in *food*'s own category carrying all of them
    but one, searched for without each word in turn. Foundation "Spinach,
    baby" has only "1 RACC"; "Spinach, raw" (1 cup, 30 g) measures it, and
    "Beans, white, canned" measures "Cannellini beans, canned". The
    calories stay *food*'s. Returns (relative, portion) or (None, None).
    """
    category = (food.get("category") or "").strip().lower()
    tokens = [t for t in query_tokens if t]
    if not category or len(tokens) < 2:
        return None, None
    pool = list(foods)
    for i in range(len(tokens)):
        pool.extend(_search_usda_for_ingredient(" ".join(tokens[:i] + tokens[i + 1:])))
    food_tokens = set(normalise(food.get("raw_description") or food["display_name"]).split())
    best, best_key, best_portion, seen = None, None, None, set()
    for cand in pool:
        if cand["fdc_id"] in seen or cand["fdc_id"] == food["fdc_id"]:
            continue
        seen.add(cand["fdc_id"])
        if (_data_type_rank(cand) < 3 or not cand.get("energy_kcal")
                or (cand.get("category") or "").strip().lower() != category):
            continue
        portion = _density_portion(cand, unit, search)
        if portion is None or _names_other_variant(search, cand):
            continue
        label_tokens = (set(normalise(cand["display_name"]).split())
                        | set(normalise(cand.get("raw_description", "")).split()))
        kept = [tok for tok in tokens if _token_in_label(tok, label_tokens)]
        if len(kept) < len(tokens) - 1:
            continue
        # Scored on the words it carries: "spinach" finds "Spinach, raw"
        # (its head) over "Spinach souffle".
        reduced = " ".join(kept)
        rank = _layer1_rank(reduced, cand)
        is_head = rank[0] == 4
        # Then the same form as *food* ("drained" beans weigh less a cup).
        overlap = len(food_tokens & set(normalise(cand.get("raw_description") or cand["display_name"]).split()))
        key = (len(kept), is_head, overlap, rank)
        if best is None or key > best_key:
            best, best_key, best_portion = cand, key, portion
    return best, best_portion


def _density_portion(food: dict, unit: str, line: str) -> dict | None:
    """
    *food*'s volume portion to measure [unit] by, for another food: a plain
    one ("1 cup", "1 tbsp"), in [unit] if there is one, else one whose other
    words the [line] says ("cup, chopped" for "chopped green beans"). Never
    one measuring another form ("1 cup, whipped" weighs half a cup of cream).
    For a count unit, its count portion ("1 medium" first, for pieces).
    """
    if unit.lower() not in VOLUMETRIC_UNITS:
        keywords = PORTION_UNIT_KEYWORDS.get(unit.lower()) or PORTION_UNIT_KEYWORDS["piece"]
        counted = [(i, p) for p in food.get("portions", []) if p.get("gram_weight")
                   and not _is_basis_portion(p)
                   for i, kw in enumerate(keywords)
                   if re.search(rf"\b{re.escape(kw)}", (p.get("label") or "").lower())]
        return min(counted, key=lambda x: (x[0], bool(SIZED_LABEL_RE.search(
            x[1].get("label") or ""))))[1] if counted else None
    target = _normalise_volume_unit(unit)
    usable = [p for p in food.get("portions", [])
              if p.get("gram_weight") and not _is_basis_portion(p)
              and _portion_label_unit(p.get("label", "")) in VOLUME_TO_TSP
              and _portion_fit(p["label"], line) < 3]
    if not usable:
        return None
    return min(usable, key=lambda p: (_portion_fit(p["label"], line),
                                      _portion_label_unit(p["label"]) != target))


# A cuisine word leading an ingredient ("Thai basil", "Italian sausage").
LOCATION_PREFIXES = {
    "thai", "chinese", "japanese", "korean", "vietnamese", "filipino",
    "italian", "french", "greek", "mexican", "indian", "spanish",
    "middle eastern", "persian", "turkish", "lebanese", "moroccan",
    "indonesian", "malaysian", "taiwanese", "cantonese", "szechuan",
    "sichuan", "cambodian", "burmese", "dutch", "german", "portuguese",
    "american", "british", "australian", "african", "caribbean",
}


# Leading words that describe a state, not a food: when "dry white wine" or
# "melted butter" finds nothing, the food is "white wine" / "butter".
FALLBACK_DROP_WORDS = {
    # "uncooked": branded pasta is dry and never says so ("LINGUINE"); USDA
    # lists only some shapes (food_aliases), so "uncooked linguine" lands here.
    "dry", "uncooked", "melted", "softened", "cold", "warm", "hot", "chilled", "room",
    "temperature", "fresh", "plain", "regular", "good", "quality",
    # Forms the parser keeps since 22 Oct 2026 ("dried mung beans": USDA's
    # dry beans are "mature seeds, raw" and never say dried).
    "dried", "frozen", "crushed", "grated", "shredded", "diced", "toasted", "roasted",
}


# A word at least this long may be respelled one letter off (_respelled).
RESPELL_MIN_LETTERS = 5
# Recipe words that are a cut or state, not a food: "cubed" is one letter
# from "cubes", "pitted" from "potted".
NOT_RESPELLED = {
    "cubed", "pitted", "sweetened", "unsweetened", "unflavored", "shaved",
    "seeded", "halved", "trimmed", "packed", "boneless", "skinless", "chunks",
    "strips", "wedge", "wedges", "slice", "slices", "threads", "matchsticks",
}


def _respelled(ingredient: str, boost_rules=None, category: str = "") -> str:
    """
    [ingredient] with a word no USDA food carries replaced by the one-letter-
    off spelling USDA uses: "cremini mushrooms" -> "crimini mushrooms"
    (USDA "Mushrooms, brown, italian, or crimini, raw"; the line matched
    branded "STUFFED CREMINI MUSHROOMS", 22 Oct 2026), "mozarella" ->
    "mozzarella". Only words of RESPELL_MIN_LETTERS or more, so "beer"
    never becomes "beef" nor "pears" "peas"; candidates come from
    search_food_names_by_spelling. Unchanged when a boost rule names the
    line (rules are written for its spelling) or nothing qualifies.
    """
    rules = BUILTIN_BOOSTS if boost_rules is None else boost_rules
    boosted, _, pinned = apply_boosts(ingredient, rules, category)
    if pinned or boosted.lower() != ingredient.lower():
        return ingredient
    query = normalise(strip_prep(ingredient))
    words = [w for w in query.split()
             if len(w) >= RESPELL_MIN_LETTERS and w not in GENERIC_QUERY_TOKENS
             and w not in PREP_WORDS and w not in FALLBACK_DROP_WORDS
             and w not in NOT_RESPELLED]
    if not words:
        return ingredient

    def name_tokens(foods) -> set[str]:
        tokens = set()
        for f in foods:
            for t in normalise(f"{f.get('display_name', '')} {f.get('raw_description') or f.get('description') or ''}").split():
                tokens.update((t, _canonical_token(t)))
        return tokens

    known = name_tokens(_search_usda_for_ingredient(query))
    respelled = ingredient
    for word in words:
        if word in known or _canonical_token(word) in known:
            continue
        # The line's search can find nothing ("lemon wedge"); the word's own
        # search says whether USDA has it.
        own = name_tokens(_search_usda_for_ingredient(word))
        if word in own or _canonical_token(word) in own:
            continue
        rows = supabase_search_food_names_by_spelling(word)
        found = name_tokens(rows)
        if word in found or _canonical_token(word) in found:
            continue  # USDA has the word itself
        # From a food that also has the line's other words: "crimini" comes
        # with "mushrooms", but "grass" never with "noodles" ("glass
        # noodles"), nor "dripping" with "tempura" ("tempura dipping sauce").
        others = {_canonical_token(w) for w in words if w != word}
        rows = [row for row in rows if others <= name_tokens([row])]
        close = Counter(
            t for row in rows
            for t in set(normalise(f"{row.get('display_name', '')} {row.get('description') or ''}").split())
            if len(t) >= RESPELL_MIN_LETTERS
            and (_one_edit_apart(word, t) or _one_edit_apart(_canonical_token(word), _canonical_token(t)))
            and _canonical_token(t) != _canonical_token(word))
        if close:
            spelling = max(sorted(close), key=lambda t: close[t])
            respelled = re.sub(rf"(?i)\b{re.escape(word)}\b", spelling, respelled)
    return respelled


# The food search (27 Oct 2026, stage 3 of unifying the app's search and
# this matcher): food_name_search, the port of the app's search, names the
# foods (layer 1); _match_ingredient_once is the recipe layer on top (layer
# 2). This module's own name search, scoring and shortcuts went with it.
# Match results by line: repeated ingredients across recipes search once.
_MATCH_CACHE: dict[tuple, tuple] = {}
# A score for match_ingredient's callers by layer 1's rank tier: a USDA
# head match (4), a display-name match (3, 2), words only (1), or a name
# that only describes another food (demoted below 1).
_TIER_SCORE = {4: 0.95, 3: 0.9, 2: 0.75, 1: 0.5}
NAMED_PRODUCT_SCORE = 0.85
# Layer 1's best rows the recipe layer re-ranks; it never reaches further.
RERANK_LIMIT = 30
# Words a line says about the food's state or quality, not which food:
# searched without when layer 1's best row doesn't carry one ("cooked
# linguine" found "SEAFOOD LINGUINE"). "hot" stays ("hot dog", "hot green
# chili").
RECIPE_STATE_WORDS = (PREP_WORDS | FALLBACK_DROP_WORDS | set(SEARCH_RULES["cooking_words"]["words"])
                      | {"uncooked", "dry", "organic", "large", "small", "medium", "canned"}) - {"hot"}
# Of those, the ones that never name a product: searched without too when
# that puts layer 1's best row in a higher tier and the line isn't a head
# match ("fresh ginger" found a vinaigrette, "Ginger root, raw" doesn't say
# fresh). Not "toasted", "dried" or "frozen": "TOASTED COCONUT" is the
# product, and layer 1 reads them in a qualifier (state_words).
RECIPE_QUALITY_WORDS = (RECIPE_STATE_WORDS - PRODUCT_PREP_WORDS
                        - (food_name_search.STATE_WORDS - {"fresh", "raw"})
                        - {"ground", "dry", "unripe", "seasoned", "blanched"})
# A line asking for the food uncooked: USDA says "raw", or "uncooked", or
# "dry" (pasta, noodles, grits).
RAW_LINE_RE = re.compile(r"(?i)\b(?:raw|uncooked|dry)\b")
# How a cut's bone and skin are said in a line. USDA never says "bone-in"
# or "skin-on", so no row carries every word of "bone-in beef shank": the
# search goes without them. For a chicken cut, _chicken_cut reads all of
# these and the search goes without each ("boneless skin-on chicken thigh"
# found boneless skinless thighs, the only rows saying boneless).
BONE_IN_SKIN_ON_RE = re.compile(
    r"(?i)\b(?:bone[- ]?in|skin[- ]?on|heads?[- ]?on|shells?[- ]?on|unpeeled|in (?:the )?shells?)\b")
CUT_BONE_SKIN_RE = re.compile(
    r"(?i)\b(?:bone[- ]?in|boneless|skin[- ]?on|skin[- ]?off|skinless|with(?:out)? skin|no skin)\b")
# How a meat line counts its meat, which no USDA meat says: "1 lb boneless
# skinless chicken pieces" found breaded fried boneless pieces.
MEAT_PIECE_RE = re.compile(r"(?i)\b(?:pieces?|chunks?|bite[- ]?sized?|cut up)\b")
_SKIN_ROW_RE = re.compile(r"\b(?:meat and skin|with skin|skin eaten|skin coating eaten)\b")
_SKINLESS_ROW_RE = re.compile(r"\b(?:skinless|meat only|skin not eaten)\b")


def _layer1(text: str) -> tuple[list[dict], food_name_search.SplitQuery, food_name_search.Query]:
    rows, split = food_name_search.search(text, limit=60)
    return rows, split, food_name_search.Query.parse(split.food)


def _top_rank(found) -> food_name_search.Rank:
    rows, _, query = found
    return food_name_search.score_row(query, rows[0]) if rows else food_name_search.NONE


def _row_words(row: dict) -> set[str]:
    return {_canonical_token(t) for t in
            normalise(f"{row.get('display_name') or ''} {row.get('description') or ''}").split()}


def _recipe_rows(text: str):
    """
    Layer 1's rows for a recipe line's name: with RECIPE_STATE_WORDS the best
    row doesn't carry left out; with RECIPE_QUALITY_WORDS left out too when
    that puts the best row in a higher tier than a search short of a head
    match; and without a leading cuisine word USDA doesn't carry when the
    rest is a USDA food with nothing added ("Japanese mayonnaise" is
    "Mayonnaise, regular", not "JAPANESE SPICY MAYO"). Returns (rows, split,
    query).
    """
    found = _layer1(text)
    rows, _, query = found
    words = query.normalized.split()
    if not rows:
        # No row has every word: without the state words and "cut" ("cut
        # yardlong beans" is "Yardlong bean, raw"). Not a cooking word: dry
        # glass noodles by the cooked cup tripled sotanghon soup.
        kept = [w for w in words if (w not in RECIPE_STATE_WORDS or COOKING_WORD_RE.fullmatch(w))
                and w != "cut"]
        if kept and len(kept) < len(words):
            return _layer1(" ".join(kept))
        return found
    top = _top_rank(found)
    carried = _row_words(rows[0])
    missing = [w for w in words if w in RECIPE_STATE_WORDS and _canonical_token(w) not in carried]
    if missing and len(missing) < len(words):
        retry = _layer1(" ".join(w for w in words if w not in missing))
        if retry[0] and _top_rank(retry).tier >= top.tier:
            found = retry
            words = found[2].normalized.split()
            top = _top_rank(found)
    quality = [w for w in words if w in RECIPE_QUALITY_WORDS]
    if top.tier < 4 and quality and len(quality) < len(words):
        retry = _layer1(" ".join(w for w in words if w not in quality))
        if retry[0] and _top_rank(retry).tier > top.tier:
            found = retry
            words = found[2].normalized.split()
            top = _top_rank(found)
    if len(words) > 1 and words[0] in LOCATION_PREFIXES and (top.tier < 4 or top.bucket < 1000):
        retry = _layer1(" ".join(words[1:]))
        best = _top_rank(retry)
        if retry[0] and best.tier == 4 and best.bucket >= 1000:
            found = retry
    return found


def _chicken_cut(line: str) -> tuple[str | None, bool | None]:
    """The chicken cut a line names and whether it's skinless, as the
    CHICKEN_CUT_* lists read them: breast is skinless
    unless the line says skin, other cuts keep it unless it says skinless."""
    low = line.lower()
    if not re.search(r"\bchicken\b", low) or any(ex in low for ex in CHICKEN_CUT_EXCLUDES):
        return None, None
    cut = next((c for c in CHICKEN_CUTS if re.search(rf"\b{c}s?\b", low)), None)
    if cut is None:
        return None, None
    skinless = any(t in low for t in CHICKEN_CUT_SKINLESS_TRIGGERS) or (
        cut in CHICKEN_CUT_SKINLESS_BY_DEFAULT and not any(t in low for t in CHICKEN_CUT_SKIN_ON_TRIGGERS))
    return cut, skinless


def _recipe_variant_delta(query, row: dict, line_cooked: bool, skinless: bool | None,
                          raw_known: bool = False) -> int:
    """Variants the recipe counts that layer 1 doesn't, less any it counts
    that the recipe asked for: a row's cooking state (one variant, however
    many cooking words; none for a cooked line, see COOKING_WORD_RE), and
    the skin of a chicken cut (_chicken_cut), ground meat for a meat line
    that doesn't say ground. FNDDS foods are as eaten, so
    one that doesn't say raw is cooked when another row says raw
    (*raw_known*): "Pork, ground" (299 kcal) isn't "Pork, fresh, ground,
    raw" (263)."""
    if food_name_search.is_branded_row(row):
        return 0
    desc = normalise(row.get("description") or "")
    wanted = {_canonical_token(t) for t in query.tokens}
    if not wanted or not wanted <= {_canonical_token(t) for t in desc.split()}:
        return 0
    delta = 0
    cooked = any(not ({_canonical_token(w) for w in m.group(0).split()} & wanted)
                 for m in COOKING_WORD_RE.finditer(desc))
    fndds = "survey" in (row.get("data_type") or "").lower()
    # FNDDS's "from canned", "from frozen", "from dried" are cooked dishes:
    # "Kidney beans, from canned, no added fat" is 135 kcal, the canned
    # beans 84 (27 Oct 2026).
    as_eaten = fndds and ((raw_known and not _says_raw(query, row))
                          or bool(FNDDS_FROM_RE.search(desc)))
    if not line_cooked and (cooked or as_eaten):
        delta += 1
    # A meat line's meat isn't ground unless it says so: "1 lb chicken" found
    # "Chicken, ground", "ground" being a standard word for spices.
    if wanted & GROUND_MEAT_WORDS and "ground" not in wanted and "ground" in desc.split():
        delta += 1
    if skinless is not None:
        has_skin = bool(_SKIN_ROW_RE.search(desc))
        counted = (bool(wanted & SKINLESS_BY_DEFAULT_CUTS) and "skin" not in wanted
                   and bool(SKIN_ON_RE.search(desc)))
        if skinless and has_skin and not counted:
            delta += 1
        elif not skinless:
            delta += bool(_SKINLESS_ROW_RE.search(desc)) - counted
    return delta


# Words two USDA rows of one food can differ by: "Egg, whole, raw" (FNDDS)
# and "Egg, whole, raw, fresh" (SR Legacy), "Chicken, thigh, meat and skin,
# raw" (Foundation) and "Chicken, broilers or fryers, thigh, ..." (SR).
SAME_FOOD_IGNORED = {"raw", "fresh", "broiler", "broilers", "or", "fryer", "fryers"}


def _same_food(row: dict, rank) -> tuple:
    """Rows layer 1 ranks alike that are one food in several datasets: the
    same tier and bucket, and the same description but for
    SAME_FOOD_IGNORED (USDA's notes left out). A branded product is its
    name."""
    if food_name_search.is_branded_row(row):
        words = normalise(row.get("display_name") or "")
    else:
        words = frozenset(_canonical_token(t)
                          for seg in food_name_search.usda_segments(row.get("description") or "")
                          for t in normalise(seg).split()) - SAME_FOOD_IGNORED
    return rank.tier, rank.bucket, words


FNDDS_FROM_RE = re.compile(r"\bfrom (?:canned|frozen|dried|dry|fresh|raw)\b")


# FNDDS names its restaurant dishes: "Potato, mashed, from restaurant".
FNDDS_RESTAURANT_RE = re.compile(r"\bfrom (?:restaurant|fast food|school lunch)\b")


def _is_dish_or_mix(query, row: dict, food: dict, rank) -> bool:
    """A restaurant or fast-food dish that's more than the line names
    ("Chili, Applebee's"; not "Pepperoni pizza, 14\"" for pepperoni pizza),
    or a USDA mix ("Chicken, fried, with potatoes, ...")."""
    if ((food.get("category") or "").strip().lower() in DISH_ONLY_CATEGORIES
            or FNDDS_RESTAURANT_RE.search(normalise(row.get("description") or ""))):
        return rank.tier < 4 or rank.bucket < 1000
    if food_name_search.is_branded_row(row):
        return False
    quals = food_name_search.usda_row_head_qualifiers(
        query, row.get("description") or "", row.get("display_name") or "")
    return quals is not None and food_name_search.with_food_count(query, quals) > 0


def _says_raw(query, row: dict) -> bool:
    """A USDA row carrying the line's words that says it's uncooked."""
    if food_name_search.is_branded_row(row):
        return False
    words = _row_words(row)
    return ({_canonical_token(t) for t in query.tokens} <= words
            and bool(words & {"raw", "uncooked", "dry"}))


def _match_ingredient_once(ingredient, boost_rules=None, threshold=0.45,
                           category="", unit="", is_cooked=False):
    """
    Returns (food, score, confidence, matched_alt): the recipe layer (layer
    2) on layer 1 (food_name_search). The line's recipe conventions first
    (_recipe_remap; boosts.json through _line_boost, whose pins win when
    their food fits the line's preparations and isn't cooked for an
    uncooked line); then layer 1's best rows, re-ranked, never replaced:
    for an uncooked line a row saying so, variants only a recipe counts
    (_recipe_variant_delta), and among rows layer 1 ranks alike, one with a
    portion in the line's unit ("3 cloves garlic": SR "Garlic, raw" has a
    clove, Foundation's doesn't) and one people can measure, then a
    standard reference row (SR Legacy, Foundation) over FNDDS, as the
    matcher breaks ties (_same_food). A boost that only rewrites the search ("ginger" ->
    "ginger root": alone, layer 1 says ground ginger) is used when its best
    row ranks in a tier no lower than the line's own, or names all its
    words while the line's best has a variant ("chili pepper" -> "hot green
    chili pepper": "Green chili peppers, canned" is a head match, canned).
    A rewrite ranking lower was written for the old matcher's scoring
    ("coconut cream unsweetened" found a coconut drink). matched_alt is
    always None: layer 1 ranks a food's names itself.
    """
    rules = BUILTIN_BOOSTS if boost_rules is None else boost_rules
    cache_key = (ingredient.lower(), category.lower(), unit.lower(), bool(is_cooked), bool(rules))
    if cache_key in _MATCH_CACHE:
        return _MATCH_CACHE[cache_key]
    preparations = _line_preparations(ingredient)
    line_raw = bool(RAW_LINE_RE.search(ingredient))
    remapped, is_cooked = _recipe_remap(ingredient, category, unit, is_cooked)
    boosted_text, _, pinned_fdc_id = _line_boost(remapped, rules, category, preparations,
                                                  _fetch_food_by_fdc_id)
    # Rules are written for the line's words; a cut or size word layer 1
    # takes out ("cubed kabocha squash") mustn't hide one.
    split_food = food_name_search.split_portion_words(remapped).food
    if not pinned_fdc_id and boosted_text.lower() == remapped.lower() and split_food != normalise(remapped):
        boosted_text, _, pinned_fdc_id = _line_boost(split_food, rules, category, preparations,
                                                      _fetch_food_by_fdc_id)
        if boosted_text.lower() == split_food.lower() and not pinned_fdc_id:
            boosted_text = remapped
    if pinned_fdc_id:
        food = _fetch_food_by_fdc_id(pinned_fdc_id)
        if (food is not None and _fits_preparations(food, preparations)
                and not (line_raw and _is_cooked_food(food))):
            _MATCH_CACHE[cache_key] = (dict(food), 0.95, "high", None)
            return _MATCH_CACHE[cache_key]
        boosted_text = remapped

    cut, skinless = _chicken_cut(ingredient)

    def search_text(text):
        # "eggs, scrambled" is raw eggs to scramble (_line_preparations).
        head, _, after = text.partition(",")
        if after and all(w in PREP_WORDS or w in PRODUCT_PREP_WORDS or w in RECIPE_STATE_WORDS
                         for w in normalise(after).split()):
            text = head
        text = (CUT_BONE_SKIN_RE if cut else BONE_IN_SKIN_ON_RE).sub(" ", text)
        if GROUND_MEAT_WORDS & set(normalise(text).split()):
            text = MEAT_PIECE_RE.sub(" ", text)
        if "fillet" in ingredient.lower() and _is_fish_or_seafood_name(ingredient.lower()):
            text = re.sub(r"(?i)\bfillets?\b", " ", text)
        return " ".join(text.split())

    # By the can, the canned food: "canned" is a variant word to layer 1,
    # so "1 can chicken noodle soup" found the soup as served. Left out
    # again when no row says it.
    if unit.strip().lower() in ("can", "cans") and "canned" not in normalise(remapped).split():
        if boosted_text.lower() == remapped.lower():
            boosted_text = f"canned {boosted_text}"
        remapped = f"canned {remapped}"
    # By the cube, the cubes: "2 cubes chicken bouillon" is bouillon cubes,
    # not the broth (parse_recipe keeps "cube" in "1 beef bouillon cube").
    if unit.strip().lower() == "cube" and not re.search(r"\bcubes?\b", remapped, re.I):
        if boosted_text.lower() == remapped.lower():
            boosted_text = f"{boosted_text} cube"
        remapped = f"{remapped} cube"
    found = _recipe_rows(search_text(remapped))
    if boosted_text.lower() != remapped.lower():
        line_top = _top_rank(found)
        rewritten = _recipe_rows(search_text(boosted_text))
        best = _top_rank(rewritten)
        if rewritten[0] and (best.tier >= line_top.tier
                             or (best.tier >= 2 and line_top.bucket < 1000)):
            found = rewritten
    rows, split, query = found
    line_words = normalise(ingredient).split()
    line_cooked = is_cooked or any(COOKING_WORD_RE.fullmatch(w) or w in PRODUCT_PREP_WORDS
                                   for w in line_words)
    query_tokens = {_canonical_token(t) for t in query.tokens}

    top = rows[:RERANK_LIMIT]
    portions = load_portions_for_food_ids([int(r["id"]) for r in top]) if top else {}
    aliases = food_name_search._food_aliases()
    alias_ids = {aliases.get(food_name_search.alias_key(t)) for t in (remapped, split.food)} - {None}
    raw_known = any(_says_raw(query, r) for r in top)
    raw_meat_line = _is_raw_meat_weight_line(ingredient, unit, line_cooked)
    by_can = unit.strip().lower() in ("can", "cans")
    ranked, first_of_food = [], {}
    for i, row in enumerate(top):
        build = (_build_supabase_branded_food if food_name_search.is_branded_row(row)
                 else _build_supabase_usda_food)
        food = build(row, i, portions)
        if food is None or (food.get("energy_kcal") or 0.0) > MAX_KCAL_PER_100G:
            continue
        if _is_unasked_dish(food, query_tokens):
            continue
        rank = layer1_rank = food_name_search.score_row(query, row)
        delta = _recipe_variant_delta(query, row, line_cooked and not line_raw, skinless, raw_known)
        if delta and rank.is_match:
            rank = dataclasses.replace(rank, bucket=rank.bucket - delta * food_name_search.VARIANT_PENALTY)
        has_unit = _has_unit_portion(food, unit)
        measurable = food.get("source") != "usda" or _has_measurable_portion(food)
        says_raw = _says_raw(query, row)
        first = first_of_food.setdefault(_same_food(row, rank), i)
        key = (row.get("id") in alias_ids,  # an alias names the food, as in the app
               line_raw and says_raw,
               # A restaurant or fast-food dish, or a mix ("Chicken, fried,
               # with potatoes, vegetable, frozen meal"), is never a recipe's
               # ingredient unless nothing else is: "grilled chicken" found a
               # grilled-chicken club sandwich, "chili" Applebee's chili.
               not _is_dish_or_mix(query, row, food, layer1_rank),
               # Layer 1's own order before its rank: a row naming the
               # line's product cut ("Cheese, parmesan, grated").
               food_name_search.names_product_cut(query, row, split.product_cuts),
               not _is_specialty_row(food, query_tokens),
               rank.tier,
               # Meat bought by weight is raw: an uncooked row before a cooked
               # one measured by a generic yield ("pork shoulder" found a
               # broiled petite tender, 27 Oct 2026). Uncooked, not "says
               # raw": "Pork sausage, link/patty, unprepared" is raw too.
               not (raw_meat_line and COOKING_WORD_RE.search(_row_words_text(row))),
               rank.bucket,
               # In a tier and bucket, an uncooked line's food raw: "Italian
               # sausage, pork, mild, raw" over "Sweet Italian sausage
               # links"; then layer 1's order of foods.
               not line_cooked and says_raw,
               # By the can, canned ("1 can chicken noodle soup").
               not by_can or "canned" in _row_words(row),
               -first,
               # Among one food's rows: a portion in the line's unit, one
               # people can measure, a standard reference row.
               has_unit is not False, measurable, _data_type_rank(food), -i)
        ranked.append((key, food, rank))
    if not ranked:
        result = (None, 0.0, "none", None)
        _MATCH_CACHE[cache_key] = result
        return result
    ranked.sort(key=lambda x: x[0], reverse=True)
    cooked_pasta = _pasta_keyword(ingredient) and re.match(r"(?i)cooked\s+", ingredient)
    if cooked_pasta and not _is_cooked_food(ranked[0][1]):
        # Cooked pasta is measured as the dry pasta it was cooked from
        # (build_output_rows), so it's a product near 350 kcal/100 g: both
        # "ZITI" products are meals (235, 143), "ZITI, ENRICHED MACARONI
        # PRODUCT" is the pasta (27 Oct 2026).
        dry = [x for x in ranked if x[1].get("source") == "branded"
               and (x[1].get("energy_kcal") or 0) >= DRY_PASTA_MIN_KCAL]
        if dry and (ranked[0][1].get("energy_kcal") or 0) < DRY_PASTA_MIN_KCAL:
            ranked.remove(dry[0])
            ranked.insert(0, dry[0])
    best_key, food, rank = ranked[0]
    if food.get("source") == "branded":
        name = normalise(food["display_name"])
        same = [f for k, f, _ in ranked if k[:9] == best_key[:9] and f.get("source") == "branded"
                and normalise(f["display_name"]) == name]
        if len(same) > 1:
            # Cooked pasta: the dry product, labelled by weight.
            if cooked_pasta:
                same = [f for f in same if (f.get("energy_kcal") or 0) >= DRY_PASTA_MIN_KCAL] or same
            food = _typical_branded(same, "oz" if cooked_pasta else unit)
    # A volume is borrowed from a USDA row only, as the matcher does.
    foods = [f for _, f, _ in ranked if f.get("source") == "usda"]
    food = _volume_unit_fallback(food, foods, unit, query.normalized, list(query.tokens))
    food = dict(food)
    if cut:
        food["_cut_keyword"] = cut  # used by pick_best_portion
    # The food's meat when the line names one the yields don't ("oxtail" is
    # "Beef, oxtails"); not for a line that isn't meat ("hot dog" found
    # "Hot dog, beef", 28 Oct 2026).
    meat_line = _is_raw_meat_weight_line(remapped, unit, False)
    meat_kw = _meat_keyword(remapped) or (
        _meat_keyword(food.get("raw_description") or "") if meat_line else None)
    if not is_cooked and (meat_kw or meat_line):
        meat_yield = _cooked_meat_yield(food, meat_kw)
        if meat_yield:
            food["_yield_factor"] = meat_yield
            food["_meat_keyword"] = meat_kw
    score = _TIER_SCORE.get(rank.tier, 0.3) if rank.bucket > 0 else 0.3
    # A product named with every word of the line ("MIRIN SWEET COOKING RICE
    # WINE" for mirin) is a sure match, though branded rows rank in tier 1.
    if rank.tier == 1 and rank.bucket > 0 and rank.exact == len(query.tokens) > 0:
        score = max(score, NAMED_PRODUCT_SCORE)
    result = (food, score, "high" if score >= 0.55 else "low", None)
    _MATCH_CACHE[cache_key] = result
    return result


def match_ingredient(ingredient, boost_rules=None, threshold=0.45,
                     category="", unit="", is_cooked=False):
    """
    Returns (food, score, confidence, matched_alt); see
    _match_ingredient_once. When nothing matches, retries before giving up:
      1. without the boost rules, if one rewrote the ingredient (a rule whose
         target was renamed in the data must not hide the plain match);
      2. without leading FALLBACK_DROP_WORDS ("dry white wine" -> "white
         wine").
    """
    # The parser counts "4 chicken drumstick" in drumsticks, leaving
    # "chicken" (or "bone-in skin-on chicken", unmatched) to search; the cut
    # picks the food (23 Oct 2026).
    if (unit.lower() in CHICKEN_CUTS and re.search(r"(?i)\bchicken\b", ingredient)
            and unit.lower() not in ingredient.lower()):
        ingredient = f"{ingredient} {unit.lower()}"
    # "1 whole chicken" is a whole bird, not one chicken-something: the
    # parser's "whole" unit left "chicken", roasted breast by the cup.
    if unit.lower() == "whole" and re.fullmatch(r"(?i)(?:roasting\s+)?(?:chicken|duck|turkey)", ingredient.strip()):
        ingredient = f"whole {ingredient.strip()}"
    respelled = _respelled(ingredient, boost_rules, category)
    if respelled != ingredient:
        result = match_ingredient(respelled, boost_rules, threshold, category, unit, is_cooked)
        if result[0] is not None:
            return ({**result[0], "_respelled": respelled},) + tuple(result[1:])
    # USDA never says "uncooked": dry rice is "raw", dry noodles and grits
    # "dry". "uncooked long grain white rice" lost the word and defaulted to
    # cooked rice, "uncooked egg noodles" and "uncooked grits" found cooked
    # foods (23 Oct 2026). Other pasta keeps its word: its dry form is the
    # packaged product, which never says dry (FALLBACK_DROP_WORDS).
    if re.search(r"(?i)\buncooked\b", ingredient):
        rest = re.sub(r"(?i)\s*\buncooked\b\s*", " ", ingredient).strip()
        state = ("raw" if _rice_keyword(rest)
                 else "dry" if re.search(r"(?i)\b(?:noodles?|grits)\b", rest) else "")
        if state:
            retry = match_ingredient(f"{state} {rest}", boost_rules, threshold,
                                     category, unit, is_cooked)
            if retry[0] is not None:
                return retry
    result = _match_ingredient_once(ingredient, boost_rules, threshold,
                                    category, unit, is_cooked)
    if result[0] is not None:
        return result
    rules = BUILTIN_BOOSTS if boost_rules is None else boost_rules
    if apply_boosts(ingredient, rules, category)[0].lower() != ingredient.lower():
        retry = _match_ingredient_once(ingredient, [], threshold,
                                       category, unit, is_cooked)
        if retry[0] is not None:
            return retry
    words = ingredient.split()
    drop = 0
    while drop < len(words) - 1 and words[drop].lower() in FALLBACK_DROP_WORDS:
        drop += 1
    if drop:
        retry = match_ingredient(" ".join(words[drop:]), boost_rules, threshold,
                                 category, unit, is_cooked)
        if retry[0] is not None:
            return retry
    return result


def _recipe_remap(ingredient: str, category: str, unit: str, is_cooked: bool) -> tuple[str, bool]:
    """
    The name a recipe line means, and whether it's cooked: plain rice is
    cooked rice of its grain or colour (read as cooked), INGREDIENT_REMAP's
    names, "chili" by the cup the dish. Both name searches start from it.
    """
    ing_lower = ingredient.lower()
    is_japanese_category = "japanese" in category.lower()
    rice_default_cooked = False
    if (_rice_keyword(ingredient) and not any(raw_kw in ing_lower for raw_kw in ("raw", "uncooked", "dry"))
            and not _line_preparations(ingredient) - {"cooked"}):
        rice_default_cooked = True
        is_cooked = True

    # Ingredient remaps (e.g. peppercorns -> black pepper ground)
    remapped = ingredient
    if rice_default_cooked:
        if any(kw in ing_lower for kw in ("short grain", "short-grain")):
            remapped = "cooked short grain white rice"
        elif any(kw in ing_lower for kw in ("medium grain", "medium-grain")):
            remapped = "cooked medium grain white rice"
        elif any(kw in ing_lower for kw in ("long grain", "long-grain")):
            remapped = "cooked long grain white rice"
        elif "glutinous" in ing_lower:
            remapped = "cooked glutinous white rice"
        elif any(kw in ing_lower for kw in ("jasmine", "basmati")):
            remapped = "cooked rice"
        elif (colour := next((c for c in ("brown", "wild", "black", "red")
                              if re.search(rf"\b{c}\b", ing_lower)), None)):
            # "1 cup brown rice" was cooked white rice (23 Oct 2026).
            remapped = f"{colour} rice cooked"
        elif is_japanese_category:
            remapped = "cooked medium grain white rice"
        else:
            remapped = "white rice long grain cooked"
    for trigger, replacement in INGREDIENT_REMAP.items():
        if trigger in ingredient.lower():
            remapped = replacement
            break
    # "chili" by the cup or can is the dish; by count it's the pepper ("2
    # red chili"). It was always the pepper (23 Oct 2026); the shared search
    # alone finds the dish, white chili (27 Oct 2026).
    if normalise(ingredient) in ("chili", "chilli"):
        if unit.strip().lower() in ("cup", "cups", "can", "cans", "bowl", "bowls", "qt", "quart"):
            remapped = "chili con carne with beans"
        elif unit.strip().lower() in ("", "piece", "pieces", "whole"):
            remapped = "red hot chili pepper"
    return remapped, is_cooked


def _line_boost(remapped: str, boost_rules, category: str, preparations: set[str],
                find_pinned) -> tuple[str, float, str | None]:
    """
    apply_boosts for a recipe line. A boost that loses the line's preparation
    stands aside, rewritten search and all: the potato pin took "mashed
    potatoes" to raw potatoes, the "egg" rule rewrote "fried egg" as "egg raw
    fresh". One that keeps it, in its search or its pinned food (looked up
    with *find_pinned*), stays.
    """
    boosted_text, boost_weight, pinned_fdc_id = apply_boosts(remapped, boost_rules, category)
    if preparations and boosted_text.lower() != remapped.lower():
        keeps = preparations <= set(normalise(boosted_text).split())
        if pinned_fdc_id:
            pinned = find_pinned(pinned_fdc_id)
            keeps = keeps or (pinned is not None and _fits_preparations(pinned, preparations))
        if not keeps:
            return remapped, 0.0, None
    return boosted_text, boost_weight, pinned_fdc_id


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Excel output (openpyxl)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

try:
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
    AMBER_FILL    = PatternFill("solid", fgColor="F4CCCC")
    PINK_FILL     = PatternFill("solid", fgColor="FFB3B3")
    HEADER_FILL   = PatternFill("solid", fgColor="4472C4")
    SUBTOTAL_FILL = PatternFill("solid", fgColor="D9E1F2")
    BRANDED_FILL  = PatternFill("solid", fgColor="FFF2CC")   # light yellow â€” branded
except ImportError:
    HAS_OPENPYXL = False

OUT_COLS = {
    "template_id":1,"template_name":2,"other_names":3,"category":4,
    "component_label":5,"matched_food_name":6,"food_id":7,"portion_id":8,
    "portion_amt":9,"portion_description":10,"calories_kcal":11,"cal_tot":12,
    "sub_template_id":13,"notes":14,"section":15,
    # The unit each ingredient is measured in, at its exact weight (the
    # description rounds it), for the import's unit_label / unit_grams.
    "unit_label":16,"unit_grams":17,
    # The recipe's Servings and Serving size, so a later run can use it as a
    # base template.
    "servings":18,"serving_qty":19,"serving_unit":20,
}


def write_xlsx(output_rows, output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "templates_output"
    hdr_font  = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    body_font = Font(name="Arial", size=10)
    sub_font  = Font(bold=True, name="Arial", size=10)
    la = Alignment(horizontal="left",   vertical="center")
    ca = Alignment(horizontal="center", vertical="center")

    for col_idx, h in enumerate(OUT_COLS.keys(), start=1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.font=hdr_font; c.fill=HEADER_FILL; c.alignment=ca

    col_widths=[16,24,18,18,28,28,14,16,12,28,16,10,16,36,16]
    for i,w in enumerate(col_widths,start=1):
        ws.column_dimensions[get_column_letter(i)].width=w
    ws.row_dimensions[1].height=18
    ws.freeze_panes="C2"

    excel_row=2
    for rd in output_rows:
        rtype=rd.get("_type","data")

        if rtype=="subtotal":
            ws.cell(row=excel_row,column=OUT_COLS["template_id"],    value=rd.get("template_id",""))
            ws.cell(row=excel_row,column=OUT_COLS["component_label"],value="TOTAL")
            ws.cell(row=excel_row,column=OUT_COLS["cal_tot"],
                    value=f"=SUM(L{rd['start_row']}:L{rd['end_row']})")
            for c in range(1,len(OUT_COLS)+1):
                cell=ws.cell(row=excel_row,column=c)
                cell.fill=SUBTOTAL_FILL; cell.font=sub_font; cell.alignment=la
            excel_row+=1; continue

        if rtype=="note":
            ws.cell(row=excel_row,column=OUT_COLS["template_id"],    value=rd.get("template_id",""))
            ws.cell(row=excel_row,column=OUT_COLS["template_name"],  value=rd.get("template_name",""))
            ws.cell(row=excel_row,column=OUT_COLS["category"],       value=rd.get("category",""))
            ws.cell(row=excel_row,column=OUT_COLS["component_label"],value=rd.get("component_label",""))
            ws.cell(row=excel_row,column=OUT_COLS["notes"],          value=rd.get("notes",""))
            ws.cell(row=excel_row,column=OUT_COLS["section"],        value=rd.get("section",""))
            for c in range(1,len(OUT_COLS)+1):
                ws.cell(row=excel_row,column=c).font=body_font
                ws.cell(row=excel_row,column=c).alignment=la
            excel_row+=1; continue

        conf=rd.get("_confidence","high"); source=rd.get("_source","usda")
        if   conf=="none":                        fill=PINK_FILL
        elif source=="branded" and conf=="high":  fill=BRANDED_FILL
        elif conf=="low":                         fill=AMBER_FILL
        else:                                     fill=None

        cal_col = get_column_letter(OUT_COLS["calories_kcal"])
        amt_col = get_column_letter(OUT_COLS["portion_amt"])
        cal_tot_formula = (f"={cal_col}{excel_row}*{amt_col}{excel_row}"
                           if rd.get("calories_kcal","") != "" else "")
        fields=[
            ("template_id",         rd.get("template_id","")),
            ("template_name",       rd.get("template_name","")),
            ("other_names",         rd.get("other_names","")),
            ("category",            rd.get("category","")),
            ("component_label",     rd.get("component_label","")),
            ("matched_food_name",   rd.get("matched_food_name","")),
            ("food_id",             rd.get("food_id","")),
            ("portion_id",          rd.get("portion_id","")),
            ("portion_amt",         rd.get("portion_amt","")),
            ("portion_description", rd.get("portion_description","")),
            ("calories_kcal",       rd.get("calories_kcal","")),
            ("cal_tot",             cal_tot_formula),
            ("sub_template_id",     rd.get("sub_template_id","")),
            ("notes",               rd.get("notes","")),
            ("section",             rd.get("section","")),
            ("unit_label",          rd.get("unit_label","")),
            ("unit_grams",          rd.get("unit_grams","")),
            ("servings",            rd.get("servings","")),
            ("serving_qty",         rd.get("serving_qty","")),
            ("serving_unit",        rd.get("serving_unit","")),
        ]
        for col_name,value in fields:
            cell=ws.cell(row=excel_row,column=OUT_COLS[col_name],value=value)
            cell.font=body_font; cell.alignment=la
            if fill: cell.fill=fill
        excel_row+=1

    ws.auto_filter.ref=f"A1:{get_column_letter(len(OUT_COLS))}1"
    wb.save(output_path)
    print(f"[âœ“] Saved {output_path}")

def load_existing_xlsx(path):
    """
    Read an existing output xlsx back into the internal row-dict format
    used by build_output_rows. Returns [] if the file doesn't exist.

    Row type is inferred:
      - component_label == "TOTAL"  â†’ subtotal
      - notes starts with "to taste" â†’ note
      - otherwise                   â†’ data
    """
    if not os.path.exists(path):
        return []
    try:
        from openpyxl import load_workbook
    except ImportError:
        return []

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows = []
    headers = [ws.cell(row=1, column=c).value for c in range(1, len(OUT_COLS)+1)]

    for excel_row in range(2, ws.max_row + 1):
        vals = {headers[c]: ws.cell(row=excel_row, column=c+1).value
                for c in range(len(headers)) if headers[c]}
        if not any(vals.values()):
            continue

        comp = str(vals.get("component_label","") or "")
        notes = str(vals.get("notes","") or "")

        if comp == "TOTAL":
            # Subtotal row â€” reconstruct start/end from the SUM formula
            # We don't need them for re-writing; they get recomputed in merge.
            rows.append({
                "_type":       "subtotal",
                "_confidence": "",
                "_source":     "",
                "template_id": str(vals.get("template_id","") or ""),
                "start_row":   None,
                "end_row":     None,
            })
        elif "to taste" in notes or "no calories logged" in notes:
            rows.append({
                "_type":          "note",
                "_confidence":    "",
                "_source":        "",
                "template_id":    str(vals.get("template_id","") or ""),
                "template_name":  str(vals.get("template_name","") or ""),
                "category":       str(vals.get("category","") or ""),
                "component_label":comp,
                "notes":          notes,
                "section":        str(vals.get("section","") or ""),
                "other_names":    str(vals.get("other_names","") or ""),
                "servings":       vals.get("servings") or "",
                "serving_qty":    vals.get("serving_qty") or "",
                "serving_unit":   str(vals.get("serving_unit","") or ""),
            })
        else:
            # Infer confidence/source from notes text
            notes_lower = notes.lower()
            if "[off]" in notes_lower:
                source = "off"
            elif "[branded]" in notes_lower:
                source = "branded"
            else:
                source = "usda"
            if "unmatched" in notes_lower:
                conf = "none"
            elif "low conf" in notes_lower:
                conf = "low"
            else:
                conf = "high"

            def _str(v): return str(v) if v is not None else ""
            def _num(v):
                if v is None: return ""
                try: return float(v)
                except (ValueError, TypeError): return _str(v)

            rows.append({
                "_type":              "data",
                "_confidence":        conf,
                "_source":            source,
                "template_id":        _str(vals.get("template_id","")),
                "template_name":      _str(vals.get("template_name","")),
                "other_names":        _str(vals.get("other_names","")),
                "category":           _str(vals.get("category","")),
                "component_label":    _str(vals.get("component_label","")),
                "matched_food_name":  _str(vals.get("matched_food_name","")),
                "food_id":            _str(vals.get("food_id","")),
                "portion_id":         _str(vals.get("portion_id","")),
                "portion_amt":        _num(vals.get("portion_amt","")),
                "portion_description":_str(vals.get("portion_description","")),
                "calories_kcal":      _num(vals.get("calories_kcal","")),
                "cal_tot":            _num(vals.get("cal_tot","")),
                "sub_template_id":    _str(vals.get("sub_template_id","")),
                "notes":              _str(vals.get("notes","")),
                "section":            _str(vals.get("section","")),
                "unit_label":         _str(vals.get("unit_label","")),
                "unit_grams":         _num(vals.get("unit_grams","")),
                "servings":           _num(vals.get("servings","")),
                "serving_qty":        _num(vals.get("serving_qty","")),
                "serving_unit":       _str(vals.get("serving_unit","")),
            })
    return rows


def merge_output_rows(existing_rows, new_rows):
    """
    Replace any template_id present in new_rows, keep everything else.
    Subtotal start_row/end_row are recomputed for the merged sequence.
    """
    new_tids = {
        r.get("template_id","")
        for r in new_rows
        if r.get("_type") in ("data","note","subtotal")
    }

    kept = [r for r in existing_rows if r.get("template_id","") not in new_tids]
    merged = kept + new_rows

    # Recompute subtotal row references (header = row 1, data starts at row 2)
    excel_row = 2
    tid_data_rows = {}   # tid â†’ [excel_rows of data/note rows]
    for r in merged:
        if r.get("_type") in ("data","note"):
            tid_data_rows.setdefault(r.get("template_id",""), []).append(excel_row)
        excel_row += 1

    for r in merged:
        if r.get("_type") == "subtotal":
            tid = r.get("template_id","")
            drows = tid_data_rows.get(tid, [])
            r["start_row"] = drows[0]  if drows else None
            r["end_row"]   = drows[-1] if drows else None

    return merged


def write_csv(output_rows, csv_path):
    """Export output_rows to CSV (flat values, no formulas) for app consumption."""
    fieldnames = list(OUT_COLS.keys()) + [
        "_type","_confidence","_source","start_row","end_row"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in output_rows:
            w.writerow(row)
    print(f"[âœ“] Saved {csv_path}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Portion selection
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

VOLUMETRIC_UNITS = {"cup", "cups", "tbsp", "tablespoon", "tablespoons",
                    "tsp", "teaspoon", "teaspoons", "ml", "l", "fl oz",
                    "pint", "quart", "gallon"}

# Compare volume labels through a single base unit so tsp/tbsp/cup entries can
# match each other without requiring an exact surface unit.
VOLUME_TO_TSP = {
    "tsp": 1.0,
    "tbsp": 3.0,
    "cup": 48.0,
    "fl oz": 6.0,
    "ml": 0.202884,   # 1 tsp = 4.92892 ml
    "l": 202.884,
    "pint": 96.0,
    "quart": 192.0,
    "gallon": 768.0,
    "cubic inch": 3.3206,
}

VOLUME_UNIT_ALIASES = {
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "cups": "cup",
    "cubic inches": "cubic inch",
    "cubic inchs": "cubic inch",
    "cu in": "cubic inch",
    "in3": "cubic inch",
}


def _normalise_volume_unit(unit: str) -> str | None:
    u = unit.lower().strip()
    if not u:
        return None
    return VOLUME_UNIT_ALIASES.get(u, u if u in VOLUME_TO_TSP else None)


def _volume_to_tsp(qty: float, unit: str) -> float | None:
    u = _normalise_volume_unit(unit)
    if not u:
        return None
    factor = VOLUME_TO_TSP.get(u)
    if factor is None:
        return None
    return qty * factor


def _volume_to_ml(qty: float, unit: str) -> float | None:
    """
    Convert a volumetric quantity to milliliters for direct liquid-to-liquid
    comparisons. This keeps cup/tbsp/tsp servings aligned with ml labels.
    """
    u = _normalise_volume_unit(unit)
    if not u:
        return None
    if u == "ml":
        return qty
    if u == "l":
        return qty * 1000.0
    tsp = _volume_to_tsp(qty, u)
    if tsp is None:
        return None
    return tsp * 4.92892


def _portion_label_unit(label: str) -> str | None:
    low = label.lower()
    if re.search(r"\bml\b", low):
        return "ml"
    if re.search(r"\bl\b", low):
        return "l"
    if "tablespoon" in low or re.search(r"\btbsp\b", low):
        return "tbsp"
    if "teaspoon" in low or re.search(r"\btsp\b", low):
        return "tsp"
    if re.search(r"\bcup\b", low):
        return "cup"
    # "OZA" is FoodData Central's fluid ounce ("8 OZA" clam juice).
    if "fl oz" in low or "fluid ounce" in low or re.search(r"\boza\b", low):
        return "fl oz"
    if "cubic inch" in low or re.search(r"\bcu\.?\s*in\b", low) or re.search(r"\bin\^?3\b", low):
        return "cubic inch"
    if "pint" in low:
        return "pint"
    if "quart" in low:
        return "quart"
    if "gallon" in low:
        return "gallon"
    return None

def _portion_label_qty(label: str) -> float:
    """
    Parse the unit quantity from a USDA portion label.
    Handles the pattern "1 10 Wrappers" where the leading 1 is a serving
    count and 10 is the actual unit quantity â€” strip the leading 1 and
    return 10. For normal labels like "1.0 cup" or "10 strip", return
    the leading number directly.
    """
    # "1 serving 1/2 cup" (USDA vanilla ice cream) is half a cup; read as
    # 1, "2 cup vanilla ice cream" logged half the ice cream (23 Oct 2026).
    label = re.sub(r"(?i)^\s*1\s+serving\s+(?=\d)", "", label)
    m = re.match(r"^([\d.]+)\s+([\d.]+)\s+\S", label.strip())
    if m:
        first, second = float(m.group(1)), float(m.group(2))
        # Leading 1 or 1.0 followed by another number â†’ serving count pattern
        if abs(first - 1.0) < 1e-9:
            return second
    # Fractions and mixed numbers: "1/8 cup" is an eighth of a cup and
    # "1 1/2 cup" one and a half, not 1 cup.
    m3 = re.match(r"^(?:(\d+)\s+)?(\d+)/(\d+)\b", label.strip())
    if m3 and int(m3.group(3)) > 0:
        whole = float(m3.group(1)) if m3.group(1) else 0.0
        return whole + int(m3.group(2)) / int(m3.group(3))
    m2 = re.match(r"^([\d.]+)", label.strip())
    return float(m2.group(1)) if m2 else 1.0


def _portion_label_volume_qty(label: str) -> tuple[float, str | None]:
    """
    Return the most useful quantity/unit pair for a volumetric serving label.

    If the label includes an explicit metric amount like "1 cup (240 ml)",
    prefer that metric value so the multiplier uses the exact liquid volume.
    """
    low = label.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l)\b", low)
    if m:
        return float(m.group(1)), m.group(2)
    return _portion_label_qty(label), _portion_label_unit(label)


# ── Spoon units derived from a cup portion ────────────────────────────────
# Many USDA foods have "1 cup" but no spoon portion, so "1 tsp sesame seeds"
# came out as 0.02 cup, or the amount check below swapped it to "Quantity not
# specified". A spoon is exactly 1/16 or 1/48 of a cup by volume; checked
# against the 608 USDA foods that have both, cup/16 lands within 5% of the
# measured tablespoon 89% of the time. Those foods keep their own spoons.
SPOON_UNITS = {"tsp", "tbsp"}
# Below this many cups, a fine food reads better in spoons (0.023 cup of
# cornstarch is 1 tsp).
SPOON_SWITCH_CUPS = 0.25
# Cup labels whose extra words still describe a fine, pourable food. Anything
# else ("chopped", "pieces", "(4.86 large eggs)") measures chunks that don't
# scale down to a spoon.
FINE_CUP_WORDS = {
    "cup", "cups", "unsifted", "sifted", "dipped", "spooned", "stirred",
    "packed", "unpacked", "not", "level", "ground", "dry", "granulated",
    # Not "whipped": a cup of whipped cream is half the weight of a cup of cream.
    "powdered", "melted", "and", "or", "into",
}
# Foods measured in pieces; a spoon of them only makes sense when the recipe
# itself says spoons.
CHUNKY_CATEGORY_RE = re.compile(
    r"vegetable|fruit|beef|pork|lamb|veal|game|poultry|chicken|turkey|fish|"
    r"shellfish|seafood|meat|sausage|mixed dish|entree|omelet",
    re.IGNORECASE,
)


# Portions nobody measures with: switching away from them loses nothing.
UNMEASURABLE_PORTION_RE = re.compile(r"quantity not specified|\bracc\b", re.IGNORECASE)


AERATED_WORDS = {"whipped", "whip", "foam", "frothed", "fluffed", "popped", "puffed"}


def _portion_fit(label: str, line: str) -> int:
    """
    How well a volume portion's label measures a recipe [line]: 0 its other
    words are ones the line says ("1 cup, chopped" for "chopped green
    beans", "1 cup strips or slices" for carrot matchsticks, a cut USDA
    labels another way), 1 a plain volume ("1 cup", "2 tbsp"), 2 other words
    ("1 tsp, leaves"), 3 an aerated form the line doesn't say ("1 cup,
    whipped").
    Heavy cream in cups was measured by "1 cup, whipped", 120 g instead of
    238 (22 Oct 2026). Ties keep the food's own order.
    """
    label = re.sub(r"\([^)]*\)", " ", label.lower())
    words = [w for w in re.findall(r"[a-z]+", label) if w not in PLAIN_VOLUME_WORDS]
    said = {_canonical_token(food_name_search.CUT_LABELS.get(t, t)) for t in normalise(line).split()}
    said |= {_canonical_token(t) for t in normalise(line).split()}
    if not words:
        return 1
    # Alternatives: "strips or slices" is said when either one is.
    for i, w in enumerate(words[1:-1], 1):
        if w == "or" and {_canonical_token(words[i - 1]), _canonical_token(words[i + 1])} & said:
            said |= {_canonical_token(words[i - 1]), _canonical_token(words[i + 1])}
    if all(_canonical_token(w) in said or w in ("and", "or") for w in words):
        return 0
    return 3 if any(w in AERATED_WORDS and w not in said for w in words) else 2


def _is_fine_cup_label(label: str) -> bool:
    words = re.findall(r"[a-z]+", label.lower())
    return all(w in FINE_CUP_WORDS for w in words)


# Count labels for an unusual size of the food. Without a size in the line,
# a plain count beats them: "1 hamburger roll" took "1 miniature/small
# hamburger bun" (28 g, not 52) and American cheese "1 cracker-size slice"
# (9 g, not 21) because they came first (23 Oct 2026).
SIZED_LABEL_RE = re.compile(
    r"\b(?:miniature|mini|small|bite|cracker|snack|slider|thin|thick|large|"
    r"jumbo|extra|kids?|junior|half)\b", re.I)
# Count labels for a part of the food, not one of it ("1 slice" of avocado).
PART_LABEL_RE = re.compile(
    r"\b(?:slices?|pieces?|wedges?|strips?|cubes?|rings?|lea(?:f|ves)|sprigs?|"
    r"florets?|spears?|segments?|sections?|pats?|surface|inch|dash|pinch|"
    r"drops?|stalks?|sticks?)\b", re.I)


def _unsized_whole_portion(food: dict) -> dict | None:
    """The food's own count portion for one whole item at its usual size:
    "1 hamburger bun", "1 fruit". None when the food has its own "piece"
    portion (gyoza, candy), which a piece line keeps."""
    own = [p for p in food.get("portions", [])
           if p.get("gram_weight") and "-vol-" not in str(p.get("portion_id", ""))]
    if any(re.search(r"\bpieces?\b", (p.get("label") or "").lower()) for p in own):
        return None
    for p in own:
        label = re.sub(r"\([^)]*\)", " ", p.get("label") or "")
        if (_is_counted_portion(label) and not SIZED_LABEL_RE.search(label)
                and not PART_LABEL_RE.search(label)):
            return p
    return None


def _is_counted_portion(label: str) -> bool:
    """A piece-style portion: "block", "1 large", "slice". Not a volume, a
    weight, or USDA's unmeasurable servings."""
    low = label.lower().strip()
    if not low or UNMEASURABLE_PORTION_RE.search(low):
        return False
    if _portion_label_unit(low) is not None:
        return False
    return not re.search(r"\b(g|oz|lb|100g|serving|guideline|nlea)\b", low)


def _derived_spoon_portion(food: dict, portion: dict, portion_amt: float,
                           unit: str) -> dict | None:
    """
    A "1 tsp" or "1 tbsp" portion worked out from the food's cup portion,
    when the food has no spoon portion of its own and either the recipe
    measured in spoons, or the amount is under SPOON_SWITCH_CUPS of a fine
    food and the chosen portion is a cup or one nobody measures with. None
    when the chosen portion should stay.
    """
    portions = food.get("portions", [])
    if any(_portion_label_unit(p.get("label", "")) in SPOON_UNITS for p in portions):
        return None
    cups = [p for p in portions
            if _portion_label_unit(p.get("label", "")) == "cup" and p.get("gram_weight")]
    if not cups:
        return None
    # The chosen cup, else the plainest one.
    cup = portion if portion in cups else min(cups, key=lambda p: len(p["label"]))
    serving_qty, serving_unit = _portion_label_volume_qty(cup["label"])
    serving_tsp = _volume_to_tsp(serving_qty, serving_unit or "cup")
    if not serving_tsp:
        return None
    grams_per_tsp = cup["gram_weight"] / serving_tsp
    recipe_unit = _normalise_volume_unit(unit)
    if recipe_unit in SPOON_UNITS:
        spoon = recipe_unit
    else:
        recipe_grams = portion_amt * portion["gram_weight"]
        recipe_cups = recipe_grams / (grams_per_tsp * VOLUME_TO_TSP["cup"])
        if (recipe_cups >= SPOON_SWITCH_CUPS
                or not (portion is cup or UNMEASURABLE_PORTION_RE.search(portion["label"]))
                or not _is_fine_cup_label(cup["label"])
                or CHUNKY_CATEGORY_RE.search(food.get("category") or "")
                or any(_is_counted_portion(p.get("label", "")) for p in portions)):
            return None
        spoon = "tbsp" if recipe_cups * 16 >= 1 else "tsp"
    return {
        "portion_id": f"{cup['portion_id']}-{spoon}",
        "label": f"1 {spoon}",
        "gram_weight": grams_per_tsp * VOLUME_TO_TSP[spoon],
        "gram_col": cup.get("gram_col", ""),
        "portion_idx": cup.get("portion_idx", 1),
        "_derived_spoon": True,
    }


# A cup of water, in ml: "1 cup water" is 250 ml (Arianna, 11 Oct 2026).
# Other foods' cups are US cups, worked out from their plain volume
# measures when they list none.
WATER_ML_PER_CUP = 250.0


def _is_plain_water(food: dict) -> bool:
    """USDA water ("Beverages, water, tap, drinking", "Water, bottled,
    generic"), whose cup lines become ml (WATER_ML_PER_CUP). Not water
    chestnuts, watercress or water convolvulus."""
    description = (food.get("raw_description") or "").lower()
    return description.startswith(("water,", "beverages, water,"))


def _cup_portion_for_spoon(food: dict, portion: dict, portion_amt: float,
                           unit: str) -> dict | None:
    """
    A cup portion for a recipe measured in cups (SPOON_SWITCH_CUPS or more)
    when the chosen portion is a spoon: the food's own cup, else "1 cup"
    worked out from the spoon (16 tbsp, 48 tsp). Foods like vinegar and soy
    sauce often have only spoon portions, so "1/2 cup vinegar" came out as
    8 tablespoons. Water stays out of it (its cups are ml, see
    WATER_ML_PER_CUP). None when the chosen portion should stay.
    """
    if _normalise_volume_unit(unit) != "cup":
        return None
    spoon_qty, spoon_unit = _portion_label_volume_qty(portion.get("label", ""))
    if spoon_unit not in SPOON_UNITS or not portion.get("gram_weight"):
        return None
    spoon_tsp = _volume_to_tsp(spoon_qty, spoon_unit)
    if not spoon_tsp:
        return None
    grams_per_tsp = portion["gram_weight"] / spoon_tsp
    recipe_grams = portion_amt * portion["gram_weight"]
    if recipe_grams / (grams_per_tsp * VOLUME_TO_TSP["cup"]) < SPOON_SWITCH_CUPS:
        return None
    for p in food.get("portions", []):
        if (_portion_label_unit(p.get("label", "")) == "cup" and p.get("gram_weight")
                and _is_fine_cup_label(p["label"])):
            return p
    if _is_plain_water(food):
        return None
    return {
        "portion_id": f"{portion['portion_id']}-cup",
        "label": "1 cup",
        "gram_weight": grams_per_tsp * VOLUME_TO_TSP["cup"],
        "gram_col": portion.get("gram_col", ""),
        "portion_idx": portion.get("portion_idx", 1),
        "_derived_cup": True,
    }


# Units a recipe line can be measured in that a food's plain volume portion
# converts to, and the order the app derives them from (volume_units.dart).
RECIPE_VOLUME_UNITS = ("cup", "tbsp", "tsp", "fl oz", "ml")
PLAIN_VOLUME_WORDS = {"cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp",
                      "teaspoon", "teaspoons", "fl", "oz", "fluid", "ounce",
                      "ounces", "ml"}


def _is_plain_volume_label(label: str) -> bool:
    """'fl oz', '1 cup', '2 tbsp': a volume and nothing else. Not 'cup,
    chopped' (it measures pieces) or 'serving 8 fl oz'."""
    words = re.findall(r"[a-z]+", label.lower())
    return (bool(words) and all(w in PLAIN_VOLUME_WORDS for w in words)
            and _portion_label_unit(label) in RECIPE_VOLUME_UNITS)


def _recipe_unit_volume_portion(food: dict, portion: dict, unit: str) -> dict | None:
    """
    The food in the recipe's own volume unit, when the chosen portion is
    some other volume: "1 cup water" came out as 8 fl oz, and "4 cup water"
    as 0.95 liter, because USDA's water lists fl oz and liter but no cup. The
    food's own portion in that unit, else one worked out from its plain
    volume portions as the app does (cup, tbsp, tsp, fl oz, ml first), so
    the app finds it among its own units. Water's cups go to ml at
    WATER_ML_PER_CUP ("_cup_as_ml"). Cups and spoons are left to
    _derived_spoon_portion / _cup_portion_for_spoon. None when the chosen
    portion should stay.
    """
    target = _normalise_volume_unit(unit)
    if target not in RECIPE_VOLUME_UNITS:
        return None
    chosen = _portion_label_unit(portion.get("label", ""))
    if chosen == target or chosen in SPOON_UNITS or chosen == "cup":
        return None
    plain = [p for p in food.get("portions", [])
             if p.get("gram_weight") and _is_plain_volume_label(p.get("label", ""))]
    own = next((p for p in plain if _portion_label_unit(p["label"]) == target), None)
    if own:
        return own
    if not plain:
        return None
    cup_as_ml = target == "cup" and _is_plain_water(food)
    if cup_as_ml:
        target = "ml"
        own_ml = next((p for p in plain if _portion_label_unit(p["label"]) == "ml"), None)
        if own_ml:
            return {**own_ml, "_cup_as_ml": True, "_derived_spoon": True}
    basis = portion if portion in plain else min(
        plain, key=lambda p: RECIPE_VOLUME_UNITS.index(_portion_label_unit(p["label"])))
    qty, basis_unit = _portion_label_volume_qty(basis["label"])
    basis_ml = _volume_to_ml(qty, basis_unit or _portion_label_unit(basis["label"]) or "")
    target_ml = _volume_to_ml(1.0, target)
    if not basis_ml or not target_ml:
        return None
    return {
        "portion_id": f"{basis['portion_id']}-{target.replace(' ', '')}",
        "label": f"1 {target}",
        "gram_weight": basis["gram_weight"] / basis_ml * target_ml,
        "gram_col": basis.get("gram_col", ""),
        "portion_idx": basis.get("portion_idx", 1),
        "_derived_spoon": True,
        "_cup_as_ml": cup_as_ml,
    }


# ── Exact amounts for same-kind units ────────────────────────────────────
# A recipe amount in the same kind of unit as the chosen portion (both
# volumes, or both weights) converts by the units' fixed ratios, never through
# grams: portion weights are rounded ("2 tbsp (30ml)" is 30 g, a US 2 tbsp is
# 29.57 ml) or off (a USDA "oz" of 28.25 g), so 1/4 cup mirin over 8
# servings came out as 0.493 tbsp, not 1/2. Grams are only for calories.
WEIGHT_TO_G = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237}
# The weights recipes are written in (RECIPE_RULES.md: meat sold by weight).
HOUSEHOLD_WEIGHT_UNITS = {"oz", "lb"}
WEIGHT_UNIT_ALIASES = {"gram": "g", "grams": "g", "ounce": "oz", "ounces": "oz",
                       "lbs": "lb", "pound": "lb", "pounds": "lb"}
# A weight label is trusted when its grams are this close to what it says
# (USDA's 28.25 g "oz" is; "1 oz yields" at 20 g isn't).
WEIGHT_LABEL_TOLERANCE = 0.05
# Under this much of a volume unit, the next smaller one reads better
# (0.018 fl oz of sake is 1/9 tsp). Below 1/8 tsp it stays tsp.
STEP_DOWN_BELOW = 1 / 8
STEP_DOWN_UNIT = {"cup": "tbsp", "fl oz": "tbsp", "tbsp": "tsp"}


def _normalise_weight_unit(unit: str) -> str | None:
    u = unit.lower().strip()
    u = WEIGHT_UNIT_ALIASES.get(u, u)
    return u if u in WEIGHT_TO_G else None


def _label_measure(portion: dict) -> tuple[float, str, str] | None:
    """
    What a portion label measures, read from its leading number and unit
    with parentheticals and trailing dots ignored: "2 tbsp. (30ml)" is
    (2, "tbsp", "volume"), "cup, chopped" (1, "cup", "volume"), "4 oz"
    (4, "oz", "weight"). None for counts, for labels that don't start with
    their unit ("serving 8 fl oz"), and for weight labels whose grams don't
    match ("1 oz yields", 20 g).
    """
    label = re.sub(r"\([^)]*\)", " ", portion.get("label", "")).lower().strip()
    words = re.match(r"^\s*((?:\d+\s+)?\d+/\d+|\d*\.?\d+)?\s*(.*)$", label)
    qty_text, rest = words.group(1), words.group(2).strip()
    qty = _portion_label_qty(label) if qty_text else 1.0
    if qty <= 0:
        return None
    for two_words in ("fl oz", "fluid ounce", "fluid ounces"):
        if rest == two_words or re.match(re.escape(two_words) + r"\b", rest):
            return qty, "fl oz", "volume"
    head = re.match(r"^([a-z]+)\.?(?=$|[\s,])(.*)$", rest)
    if not head:
        return None
    word, tail = head.group(1), head.group(2).strip(" ,.")
    volume = _normalise_volume_unit(word)
    if volume in RECIPE_VOLUME_UNITS or volume in ("l", "pint", "quart", "gallon"):
        return qty, volume, "volume"
    weight = _normalise_weight_unit(word)
    if weight and not tail:
        expected = qty * WEIGHT_TO_G[weight]
        grams = portion.get("gram_weight") or 0.0
        if abs(grams - expected) <= expected * WEIGHT_LABEL_TOLERANCE:
            return qty, weight, "weight"
    return None


def _unit_kind(unit: str) -> tuple[str, str] | None:
    """A recipe unit and its kind: ("tbsp", "volume"), ("lb", "weight")."""
    weight = _normalise_weight_unit(unit)
    if weight:
        return weight, "weight"
    volume = _normalise_volume_unit(unit)
    if volume in VOLUME_TO_TSP:
        return volume, "volume"
    return None


def _oz_portion(food: dict) -> dict:
    """The food's own plain "oz" portion, else 1 oz worked out (28.35 g)."""
    for p in food.get("portions", []):
        measure = _label_measure(p) if p.get("gram_weight") else None
        if measure and measure[1] == "oz" and abs(measure[0] - 1.0) < 1e-9:
            return p
    return {
        "portion_id": f"{food['fdc_id']}-oz",
        "label": "1 oz",
        "gram_weight": WEIGHT_TO_G["oz"],
        "gram_col": "",
        "portion_idx": 1,
        "_derived_spoon": True,
    }


# What the app's amount wheel shows exactly: whole numbers plus these
# (drum_amount_picker.dart, within 0.001).
WHEEL_FRACTIONS = (0.0, 1 / 8, 1 / 4, 1 / 3, 3 / 8, 1 / 2, 5 / 8, 2 / 3, 3 / 4, 7 / 8, 1.0)
# Units an off-wheel amount may move to, in order, and the amounts each
# reads naturally at: tsp under a tbsp, tbsp from 1 up to a quarter cup,
# cups from a quarter cup.
WHEEL_UNITS = ("tsp", "tbsp", "cup")
WHEEL_UNIT_RANGE = {"tsp": (STEP_DOWN_BELOW, 3.0), "tbsp": (1.0, 4.0),
                    "cup": (SPOON_SWITCH_CUPS, float("inf"))}


def fits_wheel(qty: float) -> bool:
    """Whether the app's wheel shows [qty] exactly (amountFitsWheel)."""
    rem = qty - int(qty)
    return qty > 0 and any(abs(rem - f) < 0.001 for f in WHEEL_FRACTIONS)


# A pinch is 1/16 tsp (Arianna, 20 Oct 2026): amounts under 1/8 tsp of
# salt or pepper read as 1 pinch, 1/2 pinch, not 0.0625 tsp.
PINCHES_PER_TSP = 16


PINCH_LABEL = "1 pinch"


def _pinch_portion(portion: dict, measure: tuple[float, str, str]) -> dict:
    """1 pinch of the food, from its tsp portion: the same grams per tsp,
    so grams and calories don't move."""
    return {
        "portion_id": f"{portion['portion_id']}-pinch",
        "label": PINCH_LABEL,
        "gram_weight": portion["gram_weight"] / measure[0] / PINCHES_PER_TSP,
        "gram_col": portion.get("gram_col", ""),
        "portion_idx": portion.get("portion_idx", 1),
        "_derived_spoon": True,
        "_pinch": True,
        "_tsp_label": portion["label"],
        "_tsp_qty": measure[0],
    }


def _unit_calories(portion: dict, food: dict) -> float:
    """Calories in one [portion], to 0.1 kcal; a pinch is a 16th of its
    teaspoon's rounded figure, so its rows add up as the tsp ones did."""
    kcal = food.get("energy_kcal", 0.0)
    if portion.get("_pinch"):
        tsp_grams = portion["gram_weight"] * PINCHES_PER_TSP
        return round(round(tsp_grams / 100 * kcal, 1) / PINCHES_PER_TSP, 6)
    return round((portion["gram_weight"] / 100) * kcal, 1)


def _water_ml_to_spoons(row: dict) -> dict:
    """A base template's cup of water (250 ml), copied in under
    SPOON_SWITCH_CUPS (Dashi Stock's water in Tamagoyaki), in tbsp, or tsp
    under 1/8 tbsp, as a recipe line of that size would be."""
    if (row.get("_type") != "data" or row.get("recipe_unit") != "ml"
            or row.get("unit_label") != "1 ml" or not row.get("unit_grams")):
        return row
    cups = float(row.get("portion_amt") or 0) / WATER_ML_PER_CUP
    if not 0 < cups < SPOON_SWITCH_CUPS:
        return row
    spoon = "tbsp" if cups * 16 >= STEP_DOWN_BELOW else "tsp"
    grams = float(row["unit_grams"]) * _volume_to_ml(1.0, spoon)
    amt = cups * VOLUME_TO_TSP["cup"] / VOLUME_TO_TSP[spoon]
    cal = row.get("calories_kcal")
    if isinstance(cal, (int, float)):
        cal = round(cal * _volume_to_ml(1.0, spoon), 1)
    return {**row, "portion_id": f"{row.get('portion_id', '')}-{spoon}",
            "unit_label": f"1 {spoon}", "unit_grams": grams, "portion_amt": amt,
            "portion_description": f"1 {spoon} ({grams:.1f} g)", "recipe_unit": "cup",
            "calories_kcal": cal,
            "cal_tot": round(cal * amt, 1) if isinstance(cal, (int, float)) else row.get("cal_tot")}


def _tsp_to_pinches(row: dict) -> dict:
    """A base template's tsp row, copied in under 1/8 tsp (Dashi Stock's
    1 tsp dashi powder x 0.07 in Takoyaki), in pinches."""
    if row.get("_type") != "data" or not row.get("unit_grams"):
        return row
    measure = _label_measure({"label": row.get("unit_label", ""),
                              "gram_weight": float(row["unit_grams"])})
    amt = float(row.get("portion_amt") or 0)
    if measure is None or measure[1] != "tsp" or not 0 < amt * measure[0] < STEP_DOWN_BELOW:
        return row
    pinch = _pinch_portion({"portion_id": row.get("portion_id", ""), "label": row["unit_label"],
                            "gram_weight": float(row["unit_grams"])}, measure)
    cal = row.get("calories_kcal")
    if isinstance(cal, (int, float)):
        cal = round(cal / measure[0] / PINCHES_PER_TSP, 6)
    amt = amt * measure[0] * PINCHES_PER_TSP
    return {**row, "portion_id": pinch["portion_id"], "unit_label": PINCH_LABEL,
            "unit_grams": pinch["gram_weight"], "portion_amt": amt,
            "portion_description": f"{PINCH_LABEL} ({pinch['gram_weight']:.1f} g)",
            "calories_kcal": cal, "_tsp_label": row["unit_label"], "_tsp_qty": measure[0],
            "cal_tot": round(cal * amt, 1) if isinstance(cal, (int, float)) else row.get("cal_tot")}


def _pinches_to_tsp(row: dict) -> dict:
    """A base template's pinch row, copied in at 1/8 tsp or more (Chashu
    Pork's 1 pinch of mirin x 2 slices), back in teaspoons."""
    if (row.get("_type") != "data" or row.get("unit_label") != PINCH_LABEL
            or float(row.get("portion_amt") or 0) < STEP_DOWN_BELOW * PINCHES_PER_TSP - 1e-9):
        return row
    label = row.get("_tsp_label") or "1 tsp"
    per_tsp = PINCHES_PER_TSP * float(row.get("_tsp_qty") or 1.0)
    grams = float(row["unit_grams"]) * per_tsp
    cal = row.get("calories_kcal")
    cal = round(cal * per_tsp, 1) if isinstance(cal, (int, float)) else cal
    amt = float(row["portion_amt"]) / per_tsp
    return {**row, "portion_id": str(row.get("portion_id", "")).removesuffix("-pinch"),
            "unit_label": label, "unit_grams": grams, "portion_amt": amt,
            "portion_description": f"{label} ({grams:.0f} g)", "calories_kcal": cal,
            "cal_tot": round(cal * amt, 1) if isinstance(cal, (int, float)) else row.get("cal_tot")}


def _is_fine_volume_label(label: str) -> bool:
    """A volume of a fine or pourable food: "2 tbsp. (30ml)", "tsp, ground",
    "fl oz", "cup". Not "cup, chopped" or "tbsp slices"."""
    words = re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", label.lower()))
    return bool(words) and all(w in FINE_CUP_WORDS or w in PLAIN_VOLUME_WORDS for w in words)


def _volume_portion_in(food: dict, portion: dict, measure: tuple[float, str, str],
                       target: str) -> dict | None:
    """
    The food in [target] (cup, tbsp or tsp) instead of [portion]: its own
    plain portion in that unit, else one worked out from [portion] by volume
    when that is a plain or fine measure ("2 tbsp. (30ml)", "fl oz", "cup";
    not "cup, chopped" or, for USDA foods, a cup of produce or meat; see
    _derived_spoon_portion). None when neither is there.
    """
    for p in food.get("portions", []):
        m = _label_measure(p) if p.get("gram_weight") else None
        if m and m[1] == target and _is_fine_volume_label(p["label"]):
            return p
    if not _is_fine_volume_label(portion.get("label", "")):
        return None
    # A cup of produce or meat is chunks; a spoon of anything is a spoon.
    if (measure[1] == "cup" and food.get("source") == "usda"
            and CHUNKY_CATEGORY_RE.search(food.get("category") or "")):
        return None
    portion_tsp = _volume_to_tsp(measure[0], measure[1])
    if not portion_tsp or not portion.get("gram_weight"):
        return None
    return {
        "portion_id": f"{portion['portion_id']}-{target}",
        "label": f"1 {target}",
        "gram_weight": portion["gram_weight"] / portion_tsp * VOLUME_TO_TSP[target],
        "gram_col": portion.get("gram_col", ""),
        "portion_idx": portion.get("portion_idx", 1),
        "_derived_spoon": True,
    }


def exact_same_kind_amount(food: dict, portion: dict | None, qty: float, unit: str,
                           yield_factor: float | None = None) -> tuple[dict, float] | None:
    """
    The portion and amount for a recipe line measured in a volume or a
    weight, when they can be worked out exactly:

    - An oz or lb line is measured in ounces (the food's own "oz", else
      1 oz worked out), whatever was picked: "1.5 lb chicken thigh" over 8
      servings is 3 oz, not 0.88 thigh. Gram lines (recipes don't use them)
      only convert exactly against a weight portion. [yield_factor] is the
      raw-to-cooked factor when the food is the cooked form.
    - A volume line against a volume portion converts by fixed ratios
      (1 cup = 16 tbsp = 48 tsp, 1 fl oz = 2 tbsp). Water's cups are
      already 250 ml ("_cup_as_ml") and stay so from SPOON_SWITCH_CUPS up.
    - Under STEP_DOWN_BELOW of a cup, fl oz or tbsp steps down to tbsp, then
      tsp, when the food has that portion or one can be worked out.
    - An amount the app's wheel can't show (3/8 tbsp) moves to the unit
      where it can (1 1/8 tsp), within WHEEL_UNIT_RANGE.
    - Under 1/8 tsp is pinches (1/16 tsp each).

    None when the units are different kinds (volume to count, weight to
    volume), which still go through grams.
    """
    recipe = _unit_kind(unit)
    if recipe is None:
        return None
    recipe_unit, kind = recipe
    if kind == "weight":
        measure = _label_measure(portion) if portion is not None else None
        if measure is not None and measure[2] != "weight":
            measure = None
        if recipe_unit in HOUSEHOLD_WEIGHT_UNITS and (measure is None or measure[1] != "oz"):
            portion = _oz_portion(food)
            measure = _label_measure(portion)
        elif measure is None:
            return None
        grams = qty * WEIGHT_TO_G[recipe_unit] * (yield_factor or 1.0)
        return portion, grams / (measure[0] * WEIGHT_TO_G[measure[1]])
    if portion is None:
        return None
    if portion.get("_cup_as_ml"):
        # Water's cups are 250 ml; under SPOON_SWITCH_CUPS it is measured
        # in spoons like any other food (1/16 cup is 1 tbsp, US).
        if recipe_unit != "cup" or qty >= SPOON_SWITCH_CUPS:
            return None
        ml_qty, _ = _portion_label_volume_qty(portion["label"])
        portion = {**portion, "portion_id": f"{portion['portion_id']}-tbsp", "label": "1 tbsp",
                   "gram_weight": portion["gram_weight"] / ml_qty * _volume_to_ml(1.0, "tbsp"),
                   "_cup_as_ml": False}
    measure = _label_measure(portion)
    if measure is None or measure[2] != "volume":
        return None
    recipe_tsp = _volume_to_tsp(qty, recipe_unit)
    portion_tsp = _volume_to_tsp(measure[0], measure[1])
    if not recipe_tsp or not portion_tsp:
        return None
    amount = recipe_tsp / portion_tsp
    while amount * measure[0] < STEP_DOWN_BELOW and measure[1] in STEP_DOWN_UNIT:
        smaller = _volume_portion_in(food, portion, measure, STEP_DOWN_UNIT[measure[1]])
        if smaller is None:
            break
        portion, measure = smaller, _label_measure(smaller)
        amount = recipe_tsp / _volume_to_tsp(measure[0], measure[1])
    if not fits_wheel(amount * measure[0]):
        for target in WHEEL_UNITS:
            low, high = WHEEL_UNIT_RANGE[target]
            n = recipe_tsp / VOLUME_TO_TSP[target]
            if target == measure[1] or not (low <= n < high and fits_wheel(n)):
                continue
            other = _volume_portion_in(food, portion, measure, target)
            if other is not None:
                portion, measure = other, _label_measure(other)
                amount = recipe_tsp / _volume_to_tsp(measure[0], measure[1])
                break
    if measure[1] == "tsp" and amount * measure[0] < STEP_DOWN_BELOW:
        portion = _pinch_portion(portion, measure)
        amount = recipe_tsp * PINCHES_PER_TSP
    return portion, amount


def _branded_spoon_portion(portion: dict, unit: str,
                           recipe_grams: float = 0.0) -> dict | None:
    """
    For a branded food whose chosen portion is a spoon ("1 tsp", 5 ml), the
    same food in the recipe's spoon: "1 tbsp tempura sauce" is one 15 g
    tablespoon, not three teaspoons. Cup lines of SPOON_SWITCH_CUPS or more
    ([recipe_grams] of it) get a US cup worked out from the spoon, as USDA
    foods do (_cup_portion_for_spoon); smaller ones go to tablespoons. None
    when the chosen portion is already that spoon, or isn't one.
    """
    spoon_qty, spoon_unit = _portion_label_volume_qty(portion.get("label", ""))
    if spoon_unit not in SPOON_UNITS or not portion.get("gram_weight"):
        return None
    spoon_tsp = _volume_to_tsp(spoon_qty, spoon_unit)
    if not spoon_tsp:
        return None
    grams_per_tsp = portion["gram_weight"] / spoon_tsp
    recipe_unit = _normalise_volume_unit(unit)
    if recipe_unit in SPOON_UNITS:
        target = recipe_unit
    elif recipe_unit == "cup":
        cups = recipe_grams / (grams_per_tsp * VOLUME_TO_TSP["cup"])
        target = "cup" if cups >= SPOON_SWITCH_CUPS else "tbsp"
    else:
        return None
    if target == spoon_unit:
        return None
    return {
        "portion_id": f"{portion['portion_id']}-{target}",
        "label": f"1 {target}",
        "gram_weight": portion["gram_weight"] / spoon_tsp * VOLUME_TO_TSP[target],
        "gram_col": portion.get("gram_col", ""),
        "portion_idx": portion.get("portion_idx", 1),
        "_derived_spoon": True,
    }


# Recipe units (as parse_recipe spells them) for a packet of something, and
# the portion labels that measure one.
PACKET_UNITS = {"pack", "sachet"}
PACKET_LABEL_RE = re.compile(r"\b(?:packets?|packs?|sachets?|packages?|envelopes?|pouch(?:es)?)\b",
                             re.IGNORECASE)


def _best_any_volumetric_portion(portions: list[dict], gram_target: float | None) -> dict | None:
    """
    Find the best real serving portion whose label is volumetric, regardless
    of the recipe's surface unit.
    """
    if gram_target is None:
        return None
    best = None
    best_diff = None
    for p in portions:
        if _is_basis_portion(p):
            continue
        label_unit = _portion_label_unit(p["label"])
        if not label_unit or label_unit not in VOLUME_TO_TSP:
            continue
        diff = abs(p["gram_weight"] - gram_target)
        if best is None or diff < best_diff:
            best = p
            best_diff = diff
    return best


def _has_compatible_volumetric_serving(food: dict, unit: str) -> bool:
    """
    True when a food has a real serving that can represent the recipe's
    volumetric unit without falling back to 100g.
    """
    return _best_volumetric_portion(food.get("portions", []), unit) is not None


def _own_count_portion(food: dict, ingredient: str) -> dict | None:
    """A portion counting one of the food by its own name: "1 anchovy",
    "1 bean" for green beans. None when there is none, and for a prepared
    dish, whose "1 lasagna (8\" square)" is the whole pan."""
    if _is_dish_category(food):
        return None
    said = {_canonical_token(t) for t in normalise(ingredient).split()}
    for p in food.get("portions", []):
        m = re.match(r"^\s*1\s+([a-z]+)\s*(?:\(|$)", (p.get("label") or "").lower())
        if m and _canonical_token(m.group(1)) in said and p.get("gram_weight"):
            return p
    return None


# Portion labels for a package of the food, not one of it.
PACKAGE_LABEL_RE = re.compile(
    r"\b(?:cans?|jars?|bottles?|box(?:es)?|containers?|cartons?|tubs?|bags?|"
    r"packages?|pkgs?|packets?|pouch(?:es)?|envelopes?|sachets?)\b", re.I)


def _is_package_label(label: str) -> bool:
    return bool(PACKAGE_LABEL_RE.search(label))


def pick_best_portion(food, unit, gram_target, qty=1.0, ingredient="", 
                      boost_rules=None):
    portions = food.get("portions", [])
    if not portions:
        return None
    if food.get("source") == "off":
        serving = next(
            (p for p in portions
             if p.get("portion_idx", 0) == 1 and not _is_basis_portion(p)),
            None,
        )
        if serving:
            return serving
        # No real serving size in food data â€” check for a portion override rule
        # before falling back to 100g basis (which causes VOL UNIT MISMATCH
        # for volumetric recipe units like tbsp, tsp, cup).
        if boost_rules and ingredient:
            override = get_portion_override(ingredient, boost_rules, unit)
            if override:
                return override
        return portions[0]
    if food.get("source") == "branded":
        real_serving = next(
            (p for p in portions
             if p.get("portion_idx", 0) == 1 and not _is_basis_portion(p)),
            None,
        )
        # A boost rule for this recipe unit beats the label serving: a curry
        # roux label says "0.083 pkg" (20 g), and "1 block" against it read
        # as 12 servings, a whole box.
        if boost_rules and ingredient:
            override = get_portion_override(ingredient, boost_rules, unit,
                                            unit_rules_only=True)
            if override:
                return override
        # A weight-only serving ("1 serving", 8 g) can't measure a spoon or
        # cup line, so an override or volume portion gets the first say.
        if real_serving and not (
                unit.lower() in VOLUMETRIC_UNITS
                and _portion_label_unit(real_serving["label"]) not in VOLUME_TO_TSP):
            # Branded foods often have both a 100g basis and a package serving.
            # Prefer the actual serving so the output uses the package label
            # instead of collapsing back to an artificial 100g portion.
            return real_serving
    if boost_rules and ingredient:
        override = get_portion_override(ingredient, boost_rules, unit)
        if override:
            return override
    # "1 packet onion soup mix" is the food's "1 packet" (39 g), not its
    # first portion, "1 serving 1 tbsp" (23 Oct 2026).
    if unit.lower() in PACKET_UNITS:
        packet = next((p for p in portions if p.get("gram_weight")
                       and PACKET_LABEL_RE.search(p.get("label") or "")), None)
        if packet is not None:
            return packet
    keywords = PORTION_UNIT_KEYWORDS.get(unit.lower(), [])
    # If the line names a chicken cut (_chicken_cut), use the cut keyword to find
    # the right portion label (e.g. "1 thigh", "1 drumstick") when unit is blank.
    if food.get("_cut_keyword") and (not keywords or unit.lower() in ("piece", "pieces", "")):
        keywords = PORTION_UNIT_KEYWORDS.get(food["_cut_keyword"], [])
    # If ingredient mentions cube size (e.g. "pork 1.5 inch"), prefer cube portion labels.
    if any(kw in ingredient.lower() for kw in ("cube", "inch")):
        for p in portions:
            if any(kw in p["label"].lower() for kw in CUBE_KEYWORDS):
                p = dict(p)
                p["_cube_match"] = True
                return p
    if any(kw in ingredient.lower() for kw in ("cubed", "cube", "cubes")):
        for p in portions:
            if any(kw in p["label"].lower() for kw in CUBE_KEYWORDS):
                p = dict(p)
                p["_cube_match"] = True
                return p
    if "fillet" in ingredient.lower() and _is_fish_or_seafood_name(food.get("display_name", "")):
        for p in portions:
            if "fillet" in p["label"].lower():
                return p
    # Empty unit means a countable ingredient (e.g. "0.4 cucumbers") â€”
    # treat as "piece" so we pick a whole-unit portion (medium, large, small)
    # rather than whatever happens to be first (e.g. a slice).
    is_unitless = not keywords and not unit
    is_piece = is_unitless or unit.lower() in ("piece", "pieces", "stalk", "stalks", "whole")
    is_slice = unit.lower() in ("slice", "slices")
    if is_unitless:
        keywords = PORTION_UNIT_KEYWORDS.get("piece", [])
    # A package is never one of a count: "1 small or medium single serving
    # bag" (45 g) was a graham cracker, its "medium" taken for a size
    # (27 Oct 2026). Unless the line counts packages ("1 can").
    if keywords and not CONTAINER_LABEL_RE.search(unit) and unit.lower() not in PACKET_UNITS:
        portions = [p for p in portions if not _is_package_label(p.get("label") or "")] or portions
    if keywords:
        # For slice ingredients (e.g. bread), apply size preference:
        # default to "medium or regular" unless ingredient specifies thick/large/thin/small.
        if is_slice:
            ing_lower = ingredient.lower()
            if any(kw in ing_lower for kw in ("thick", "large")):
                preferred_slice = "large"
            elif any(kw in ing_lower for kw in ("thin", "small")):
                preferred_slice = "small"
            else:
                preferred_slice = "medium"
            for p in portions:
                if preferred_slice in p["label"].lower() and "slice" in p["label"].lower():
                    return p
            if preferred_slice == "medium":
                for p in portions:
                    if "slice" in p["label"].lower() and not SIZED_LABEL_RE.search(p["label"]):
                        return p
            # Fall through to general keyword scan if no size match
        # For unitless/piece ingredients, apply size preference logic:
        # - If the ingredient names a size (large/small/medium), try to match it first.
        # - Otherwise default to medium if available.
        # Either way fall through to the general keyword scan if nothing matched.
        if is_piece and not food.get("_cut_keyword"):
            ing_lower = ingredient.lower()
            specified_size = next((sz for sz in ("large", "small", "medium") if sz in ing_lower), None)
            # FNDDS calls a medium one "regular" ("1 regular" cucumber, 200 g),
            # and its "1 piece/slice" (10 g) came first.
            sizes = [specified_size] if specified_size else ["medium"]
            if sizes == ["medium"]:
                sizes.append("regular")
            for preferred, p in ((sz, p) for sz in sizes for p in portions):
                # Strip parenthetical content before checking â€” prevents "1.0 cup
                # (4.86 large eggs)" from matching a search for "large".
                # Use word-boundary match so "large" doesn't match "extra large".
                label_no_parens = re.sub(r"\([^)]*\)", "", p["label"]).lower().strip()
                if re.search(r"(?<!\w)" + re.escape(preferred) + r"(?!\w)", label_no_parens):
                    # Exclude labels where the preferred size is preceded by a modifier
                    # like "extra" â€” only accept bare size labels e.g. "1.0 large".
                    if not re.search(r"\b(?:extra|very|super)\s+" + re.escape(preferred), label_no_parens):
                        return p
            # No portion in the size asked for (or the default medium): one
            # whole item beats a part ("1 large avocado" took a 30 g piece).
            whole = _unsized_whole_portion(food)
            if whole is not None:
                return whole
        # For cup quantities < 0.25, prefer tbsp/tsp portions when a sane
        # portion_amt results. Bootstrap recipe_grams from the cup portion's
        # gram_weight so this works even when gram_target is None (vol solids).
        if unit.lower() in ("cup", "cups") and qty < 0.25:
            cup_p = min((p for p in portions if "cup" in p["label"].lower()),
                        key=lambda p: _portion_fit(p["label"], ingredient), default=None)
            if cup_p:
                recipe_grams = qty * cup_p["gram_weight"]
                for sub_kw in (["tablespoon","tbsp"], ["teaspoon","tsp"]):
                    for p in portions:
                        if any(kw in p["label"].lower() for kw in sub_kw):
                            sub_amt = recipe_grams / p["gram_weight"]
                            if 0.1 <= sub_amt <= 10:
                                return p
        # For cheese measured in cups, prefer shredded unless the ingredient
        # explicitly names a different prep (diced, melted, crumbled, etc.).
        CHEESE_CUP_PREPS = {"shredded","diced","melted","crumbled","grated","sliced","chopped"}
        if (unit.lower() in ("cup","cups")
                and "cheese" in food.get("display_name","").lower()):
            specified = next((prep for prep in CHEESE_CUP_PREPS if prep in ingredient.lower()), None)
            target = specified or "shredded"
            for p in portions:
                if target in p["label"].lower():
                    return p
        labelled = [p for p in portions if any(kw in p["label"].lower() for kw in keywords)]
        # A count is never a volume: "piece" is in "1 cup pieces", which
        # measured 4.5 whole mangoes as cups (27 Oct 2026).
        if unit.lower() not in VOLUMETRIC_UNITS:
            labelled = [p for p in labelled
                        if _portion_label_unit(p["label"]) not in VOLUME_TO_TSP] or labelled
        if labelled:
            if unit.lower() in VOLUMETRIC_UNITS:
                # A plain "1 cup" before "1 cup, whipped".
                return min(labelled, key=lambda p: _portion_fit(p["label"], ingredient))
            return labelled[0]
    # A count with no portion in its unit: one of the food itself ("1
    # anchovy" for "5 anchovy fillet", which took "1 can", 45 g).
    if unit.lower() not in VOLUMETRIC_UNITS and _normalise_weight_unit(unit) is None:
        own = _own_count_portion(food, ingredient)
        if own is not None:
            return own
    # Volumetric units (cup, tbsp, tsp, â€¦) with no matching labelled portion:
    # If the DB has any volumetric serving, prefer it even when the surface
    # unit is different. This lets tsp/tbsp/cup all resolve via conversion.
    if unit.lower() in VOLUMETRIC_UNITS:
        best_vol = _best_volumetric_portion(portions, unit)
        if best_vol:
            return best_vol
        if boost_rules and ingredient:
            override = get_portion_override(ingredient, boost_rules, unit)
            if override:
                return override
        # No volume portion: a serving the food has, never a borrowed cup.
        return _own_serving_for_volume(food)
    # For gram-based and other non-volumetric requests, still prefer a true
    # volumetric serving when it exists and the implied amount is reasonable.
    # This keeps labels like "1 cup" ahead of weight-style servings such as
    # "1 oz yields", while avoiding awkward matches that would compute to a
    # tiny or enormous portion amount.
    best_true_vol = _best_any_volumetric_portion(portions, gram_target)
    if best_true_vol and gram_target is not None:
        vol_amt = gram_target / best_true_vol["gram_weight"] if best_true_vol["gram_weight"] else None
        if vol_amt is not None and 0.1 <= vol_amt <= 10:
            return best_true_vol
    if boost_rules and ingredient:
        override = get_portion_override(ingredient, boost_rules, unit)
        if override:
            return override
    if gram_target is not None:
        return min(portions, key=lambda p: abs(p["gram_weight"] - gram_target))
    return portions[0]


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Core pipeline
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# The edible share of a weight bought with bone, head or shell, by how the
# line says it was bought (parse_recipe.as_bought) and the USDA food it
# matched: (as bought, food pattern on the normalised description, edible
# share of the as-bought weight, what is left out, source). By the food, not
# the line's words: "lamb shanks" or "turkey wings" aren't beef's or
# chicken's, and "wing sauce" has no bone (28 Oct 2026). USDA's nutrients
# are per 100 g of the edible part, and so are its portion weights
# ("Weights are given for edible material without refuse ... a chicken leg
# without the bone", SR28 documentation): a count needs no share, only a
# recipe's own weight as bought does (SR28's formula: edible = as purchased
# x (100 - refuse) / 100). Checked against SR28's meat-only records: its
# "1 leg" (344 g) is meat and skin, no bone.
# Shares from SR28's refuse fields, as-purchased basis (27 Oct 2026):
# - the raw thigh (05091) gives no refuse; the roasted thigh (05094) is 17%
#   bone by cooked weight, and raw meat weighs more, so a raw thigh is at
#   most 17%. Not the raw leg's 27% (05075): its back is bonier;
# - the drumstick's "bone and cartilage 33%, bone and connective tissue
#   33%" (05066) lists the bone twice: 33%;
# - a Boston butt steak "with refuse, weighing 380 g" yields 288 g (10080).
# Shrimp from USDA AH-102 (1975), p. 105: head-on to headless 57%, headless
# in shell to peeled 81%. Whole milkfish is about 60% flesh in published
# yield studies; there is no USDA figure (Arianna). Not FNRI's figures:
# FNRI declined reuse. Pork hock has no public figure, so none.
EDIBLE_SHARE = (
    ("bone-in", r"\bveal shank separable\b", 0.51, "bone", "SR 17435"),
    ("bone-in", r"\bveal shank fore and hind\b", 0.71, "bone", "SR 17276"),
    ("bone-in", r"\bbeef shank crosscuts\b", 0.60, "bone", "SR 13227"),
    ("bone-in", r"\bpork\b.*\bbackribs\b", 0.63, "bone", "SR 10192"),
    ("bone-in", r"\bpork\b.*\bspareribs\b", 0.70, "bone", "SR 10088"),
    ("bone-in", r"\bpork\b.*\bshoulder\b", 0.76, "bone", "SR 10080"),
    ("bone-in", r"\bchicken\b.*\bdrumstick\b", 0.67, "bone", "SR 05066"),
    ("bone-in", r"\bchicken\b.*\bwing\b", 0.62, "bone", "SR 05100"),
    ("bone-in", r"\bchicken\b.*\bbreast\b", 0.80, "bone", "SR 05057"),
    ("bone-in", r"\bchicken\b.*\bthigh\b", 0.83, "bone", "SR 05094"),
    ("bone-in", r"\bchicken\b.*\bleg\b", 0.73, "bone", "SR 05075"),
    ("bone-in", r"\bchicken broilers or fryers meat and skin and giblets\b", 0.69, "bone", "SR 05001"),
    ("bone-in", r"\bchicken roasting meat and skin and giblets\b", 0.73, "bone", "SR 05109"),
    ("head-on", r"\bshrimp\b", 0.57 * 0.81, "head and shell", "USDA AH-102"),
    ("shell-on", r"\bshrimp\b", 0.81, "shell", "USDA AH-102"),
    ("whole", r"\bmilkfish\b", 0.60, "head, bones and fins", "published yields"),
)


def _edible_share(food: dict, as_bought: str):
    """(edible share, what is left out, source) of a weight line bought
    with bone, head or shell, by the food it matched (EDIBLE_SHARE), else
    None. A USDA food only: a branded label's serving is as the brand weighs
    it."""
    if not as_bought or food.get("source") != "usda":
        return None
    desc = " ".join(normalise(food.get("raw_description") or food.get("display_name") or "").split())
    for bought, pattern, share, what, source in EDIBLE_SHARE:
        if bought == as_bought and re.search(pattern, desc):
            return share, what, source
    return None


def _warm_match_cache(rows_by_template, boost_rules, threshold,
                      template_index_skip=lambda row: False) -> None:
    """
    Matches every ingredient at the same time, before the (sequential) main
    loop, which then finds each result in _MATCH_CACHE. The searches a match
    needs beyond the USDA prefetch (a rewritten query, the branded fallback
    when USDA falls short) used to run one ingredient after another: about
    3/4 of a recipe's wait (9 Oct 2026). Same arguments as the main loop, so
    the same results.
    """
    jobs = {}
    for ing_rows in rows_by_template.values():
        category = ing_rows[0].get("category", "").strip()
        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient", "").strip()
            unit = ing_row.get("unit", "").strip()
            qty_raw = ing_row.get("qty", "").strip()
            if (not ingredient or template_index_skip(ing_row) or _is_aromatic_leaf(ingredient)
                    or "to taste" in unit.lower() or "to taste" in qty_raw.lower()):
                continue
            is_cooked = ing_row.get("is_cooked", "").strip().lower() in ("true", "1", "yes")
            key = (ingredient.lower(), category.lower(), unit.lower(), is_cooked)
            jobs.setdefault(key, (ingredient, category, unit, is_cooked))
    if len(jobs) < 2:
        return

    from concurrent.futures import ThreadPoolExecutor

    def warm(job):
        ingredient, category, unit, is_cooked = job
        try:
            match_ingredient(ingredient, boost_rules, threshold, category, unit,
                             is_cooked=is_cooked)
        except Exception:
            pass  # the main loop matches it again and reports any error

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(warm, jobs.values()))


def _float_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _template_refs(rows_by_template, existing_rows, published_templates):
    """Base templates a line can use, in precedence order: this run's
    recipes, earlier runs' output, then [published_templates]."""
    refs = []
    for tid, ing_rows in rows_by_template.items():
        first = ing_rows[0]
        refs.append(tref.TemplateRef(
            tid=tid, name=first.get("template_name", "").strip() or tid,
            aka=tref.parse_aka(first.get("other_names", "")),
            servings=_float_or_none(first.get("servings")) or 1.0,
            serving_qty=_float_or_none(first.get("serving_qty")),
            serving_unit=(first.get("serving_unit") or "").strip(),
            source="run", category=(first.get("category") or "").strip(),
        ))
    earlier = defaultdict(list)
    for row in existing_rows:
        tid = row.get("template_id", "")
        if tid and tid not in rows_by_template and row.get("_type") in ("data", "note"):
            earlier[tid].append(row)
    for tid, rows in earlier.items():
        first = rows[0]
        refs.append(tref.TemplateRef(
            tid=tid, name=str(first.get("template_name") or tid),
            aka=tref.parse_aka(str(first.get("other_names") or "")),
            servings=_float_or_none(first.get("servings")) or 1.0,
            serving_qty=_float_or_none(first.get("serving_qty")),
            serving_unit=str(first.get("serving_unit") or "").strip(),
            source="output", rows=rows,
            category=str(first.get("category") or "").strip(),
        ))
    return refs + list(published_templates or [])


# Leaves that flavour a dish and are mostly taken out or not eaten, with no
# food of their own in the data: "10 curry leaves" matched a coconut curry
# (2199 kcal), kaffir lime leaves limes, banana leaf a banana. They are about
# 0 kcal, so they become note rows, like "to taste": no search, no calories,
# and left out of the saved template (templates have no notes). Whole bay
# leaves too, though the data has them: they are taken out before eating
# (27 Oct 2026). Ground bay leaf is eaten.
AROMATIC_LEAVES_RE = re.compile(
    r"(?<!ground )\b(?:curry|(?:kaffir|makrut)\s+lime|lime|pandan|banana|bay)\s+lea(?:f|ves)\b", re.I)
AROMATIC_NOTE = "aromatic leaf, not eaten - no calories logged"


def _is_aromatic_leaf(ingredient: str) -> bool:
    return bool(AROMATIC_LEAVES_RE.search(ingredient or ""))


# Frying oil ("3 cups oil for frying", parse_recipe.FRYING_OIL_UNIT) is the
# pot, not what the food keeps: "3 cups" logged 1,445 kcal a serving of
# karaage. It becomes the absorbed share instead, a percent of the fried
# food's raw edible weight by coating, in tbsp in an "Absorbed oil" section.
# The rows it is a share of are marked "fried". The rates are the app
# project's fry_types table (fry_rates.py), which app.py sends to the editor
# so it can recompute the oil when the user changes the type or the rows.
ABSORBED_OIL_SECTION = "Absorbed oil"
# The unit parse_recipe gives a frying-oil line.
FRYING_OIL_UNIT = "frying oil"
OIL_GRAMS_PER_TBSP = 13.6
_BREADED_RE = re.compile(
    r"\b(panko|bread\s*crumbs?|breadcrumbs?|cracker\s*crumbs|crushed\s+crackers|"
    r"corn\s*flakes|cornflakes)\b", re.I)
_BATTER_RE = re.compile(
    r"\b(tempura|batter|beer|club\s+soda|sparkling\s+water|soda\s+water|"
    r"buttermilk)\b", re.I)
_COATING_RE = re.compile(
    r"\b(flour|starch|cornstarch|cornflour|katakuriko|cornmeal)\b", re.I)
_EGG_RE = re.compile(r"\beggs?\b", re.I)
# What goes in the oil: meat, seafood, tofu. Eggs are left out, since a
# recipe's eggs are usually the batter.
_FRIED_FOOD_RE = re.compile(
    r"\b(chicken|beef|pork|lamb|mutton|goat|veal|turkey|duck|fish|salmon|cod|"
    r"tilapia|catfish|haddock|pollock|hake|mackerel|sardines?|tuna|snapper|"
    r"bass|trout|halibut|flounder|sole|milkfish|bangus|shrimps?|prawns?|squid|"
    r"calamari|octopus|scallops?|oysters?|clams?|mussels?|crabs?|lobster|"
    r"tofu|tempeh|spam|sausages?|hot\s*dogs?|meatballs?|quail\s+eggs?)\b", re.I)
_NOT_FRIED_FOOD_RE = re.compile(
    r"\b(stock|broth|bouillon|powder|sauce|fat|seasoning|cubes?|granules|starch|flour)\b",
    re.I)
# With no meat, fish or tofu, the starchy food is what's fried (fries).
_STARCHY_FRIED_RE = re.compile(
    r"\b(potato(?:es)?|sweet\s+potato(?:es)?|plantains?|cassava|yuca|taro)\b", re.I)
# Failing those, the vegetables are (vegetable tempura, su-age eggplant).
# Watery vegetables keep about twice the oil lean meat does unbreaded.
_VEGETABLE_FRIED_RE = re.compile(
    r"\b(eggplants?|aubergines?|shishito|bell\s+peppers?|sweet\s+peppers?|mushrooms?|shiitake|maitake|"
    r"shimeji|enoki|okra|zucchini|courgettes?|squash|pumpkin|kabocha|"
    r"lotus\s+root|renkon|burdock|gobo|green\s+beans?|string\s+beans?|"
    r"asparagus|onions?|broccoli|cauliflower|carrots?|shiso|perilla)\b", re.I)
# Unbreaded fatty or skin-on cuts lose fat in the fryer: nothing absorbed.
_FATTY_CUT_RE = re.compile(
    r"\b(skin[\s-]*on|with\s+skin|belly|pata|wings?|chicharr?on)\b", re.I)


def _fry_type(ingredients: list[str]) -> str:
    """The coating the recipe's ingredients add up to."""
    text = " | ".join(ingredients)
    if _BREADED_RE.search(text):
        return "breaded"
    if _BATTER_RE.search(text) or (_COATING_RE.search(text) and _EGG_RE.search(text)):
        return "battered"
    if _COATING_RE.search(text):
        return "starch-dusted"
    return "unbreaded"


def _fried_kind(ingredient: str) -> str | None:
    """"protein", "starchy" or "vegetable" for what may go in the fryer,
    else None."""
    if _NOT_FRIED_FOOD_RE.search(ingredient):
        return None
    if _FRIED_FOOD_RE.search(ingredient):
        return "protein"
    if _STARCHY_FRIED_RE.search(ingredient):
        return "starchy"
    if _VEGETABLE_FRIED_RE.search(ingredient):
        return "vegetable"
    return None


def _absorbed_oil(ingredients: list[str], fried: list[dict]):
    """(fry type, tbsp per serving, the rows it is a share of) for a recipe's
    frying oil. [fried] holds the recipe's possible fried rows so far, each
    with "_fried_kind" and "_fried_grams". Meat, fish and tofu are what's
    fried; failing those, the starchy food; failing that, the vegetables.
    None found, or unbreaded fatty cuts (they lose fat), gives 0 tbsp and no
    rows: the user picks in the app."""
    fry_type = _fry_type(ingredients)
    rows = [r for r in fried if r["_fried_kind"] == "protein"]
    if rows:
        if fry_type == "unbreaded" and all(
                _FATTY_CUT_RE.search(r["component_label"]) for r in rows):
            rows = []
    else:
        for kind, unbreaded_type in (("starchy", "thick-cut"),
                                     ("vegetable", "unbreaded veg")):
            rows = [r for r in fried if r["_fried_kind"] == kind]
            if rows:
                if fry_type == "unbreaded":
                    fry_type = unbreaded_type
                break
    grams = sum(r["_fried_grams"] for r in rows)
    rates = fry_rates.rates()
    if fry_type not in rates:
        raise fry_rates.FryTypesUnavailable(f"No frying rate for {fry_type!r} in fry_types.")
    return fry_type, grams * rates[fry_type] / OIL_GRAMS_PER_TBSP, rows


# Messages from the last build_output_rows: lines that name no template but
# come close to one ("dashi stok"), and, when not strict, lines that named a
# template but couldn't use it.
LAST_TEMPLATE_WARNINGS: list[str] = []


def build_output_rows(recipes_path, boost_rules=None, threshold=0.45,
                      existing_rows=None, published_templates=None,
                      strict_templates=True):
    """
    Match every recipe in [recipes_path]. A line naming a base template
    (template_refs) gets the template's ingredients as a section instead of
    a food. With [strict_templates] (batch runs) a line that names a
    template but can't use it fails the run with TemplateReferenceError,
    listing every such line; otherwise (the recipe worker) it is matched as a
    food and noted in LAST_TEMPLATE_WARNINGS.
    """
    if existing_rows is None:
        existing_rows = []
    output_rows=[]
    rows_by_template=defaultdict(list)
    match_cache: dict[tuple, tuple] = {}
    with open(recipes_path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows_by_template[row.get("template_id","").strip()].append(row)

    refs = _template_refs(rows_by_template, existing_rows, published_templates)
    template_index = tref.build_index(refs)
    cuisine_index = tref.build_cuisine_index(refs)
    template_errors: list[str] = []
    LAST_TEMPLATE_WARNINGS.clear()
    processed: set[str] = set()

    def _uses_template(ing_row) -> bool:
        ref = tref.find(ing_row.get("ingredient", ""), ing_row.get("category", ""),
                        template_index, cuisine_index)
        return ref is not None and ref.tid != ing_row.get("template_id", "").strip()

    # ── Pre-fetch USDA indexes in parallel ──────────────────────────────────
    # Collect all unique search queries across all ingredients, then fire
    # them concurrently so the network round-trips overlap.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_search_queries: set[str] = set()
    for tid, ing_rows in rows_by_template.items():
        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient", "").strip()
            unit = ing_row.get("unit", "").strip()
            if ("to taste" in unit.lower() or _uses_template(ing_row)
                    or _is_aromatic_leaf(ingredient)):
                continue
            sq = normalise(strip_prep(ingredient))
            if sq:
                all_search_queries.add(sq)

    uncached = [q for q in all_search_queries
                if (q, "usda") not in _INGREDIENT_INDEX_CACHE]
    if uncached:
        sys.stderr.write(f"  Pre-fetching {len(uncached)} ingredient searches …\n")
        sys.stderr.flush()
        def _prefetch_usda(query: str):
            _search_and_build_index(query, source_set="usda")
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(_prefetch_usda, q): q for q in uncached}
            done_count = 0
            for fut in as_completed(futures):
                done_count += 1
                if done_count % 20 == 0 or done_count == len(futures):
                    bar_width = 30
                    frac = done_count / len(futures)
                    filled = int(bar_width * frac)
                    bar = "█" * filled + "░" * (bar_width - filled)
                    sys.stderr.write(f"\r  [{bar}] {done_count}/{len(futures)} searches")
                    sys.stderr.flush()
                try:
                    fut.result()
                except Exception:
                    pass  # individual failures are handled downstream
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    _warm_match_cache(rows_by_template, boost_rules, threshold, _uses_template)

    total_templates = len(rows_by_template)
    for t_idx, (tid, ing_rows) in enumerate(rows_by_template.items(), 1):
        # ── progress bar ──
        bar_width = 30
        frac = t_idx / total_templates
        filled = int(bar_width * frac)
        bar = "█" * filled + "░" * (bar_width - filled)
        template_label = ing_rows[0].get("template_name", tid).strip()
        if len(template_label) > 28:
            template_label = template_label[:25] + "..."
        sys.stderr.write(f"\r  [{bar}] {t_idx}/{total_templates}  {template_label:<28}")
        sys.stderr.flush()

        template_name=ing_rows[0].get("template_name","").strip()
        category=ing_rows[0].get("category","").strip()
        other_names=ing_rows[0].get("other_names","").strip()
        data_row_indices=[]
        # (ingredient, grams per serving) of what goes in the frying oil.
        fried: list[tuple[str, float]] = []

        def _is_frying_oil(r) -> bool:
            return r.get("unit", "").strip().lower() == FRYING_OIL_UNIT

        # Frying oil last, once the fried food's weight is known.
        for ing_row in sorted(ing_rows, key=_is_frying_oil):
            ingredient=ing_row.get("ingredient","").strip()
            qty_raw=ing_row.get("qty","").strip()
            unit=ing_row.get("unit","").strip()
            section=ing_row.get("section","").strip() or "Main"
            fry_type = None
            if _is_frying_oil(ing_row):
                fry_type, tbsp, fried_rows = _absorbed_oil(
                    [r.get("ingredient", "") for r in ing_rows
                     if not _is_frying_oil(r)], fried)
                for r in fried_rows:
                    r["fried"] = True
                qty_raw, unit, section = f"{tbsp:.4f}", "tbsp", ABSORBED_OIL_SECTION
            size_hint=ing_row.get("size_hint","").strip()
            is_cooked = ing_row.get("is_cooked","").strip().lower() in ("true","1","yes")
            # How the weight was bought (parse_recipe.as_bought); worked out
            # again for a CSV written before the column.
            as_bought = (ing_row["as_bought"].strip() if "as_bought" in ing_row
                         else parse_recipe.as_bought(unit, ingredient))
            # ingredient_for_portion: bare name + size hint so pick_best_portion
            # can prefer "medium piece", "large whole", etc. without the size
            # word polluting the fuzzy search match.
            ingredient_for_portion = f"{ingredient} {size_hint}".strip() if size_hint else ingredient

            if ("to taste" in unit.lower() or "to taste" in qty_raw.lower()
                    or (unit.lower() in ("tt","") and qty_raw in ("","0"))):
                output_rows.append({
                    "_type":"note","template_id":tid,"template_name":template_name,
                    "category":category,"component_label":ingredient,
                    "notes":"to taste â€” no calories logged",
                    "section":section,
                })
                continue

            if _is_aromatic_leaf(ingredient):
                output_rows.append({
                    "_type":"note","template_id":tid,"template_name":template_name,
                    "category":category,"component_label":ingredient,
                    "notes":AROMATIC_NOTE,
                    "section":section,
                })
                continue

            # A base template by name ("1.5 cup dashi stock"): its
            # ingredients, scaled, in a section named after it.
            ref = tref.find(ingredient, category, template_index, cuisine_index)
            if ref is not None and ref.tid != tid:
                try:
                    if ref.source == "run":
                        if ref.tid not in processed:
                            raise tref.TemplateReferenceError(
                                f"'{qty_raw} {unit} {ingredient}'".replace("  ", " ")
                                + f" uses {ref.name} before its block; move "
                                f"{ref.name} above {template_name}.")
                        ref.rows = [r for r in output_rows
                                    if r.get("template_id") == ref.tid
                                    and r.get("_type") in ("data", "note")]
                    try: line_qty = float(qty_raw) if qty_raw else 1.0
                    except ValueError: line_qty = 1.0
                    servings_used = tref.servings_of(line_qty, unit, ref)
                    copied = tref.expanded_rows(ref, servings_used, {
                        "template_id": tid, "template_name": template_name,
                        "category": category, "other_names": other_names,
                    })
                    # Scaled copies cross 1/8 tsp both ways; absorbed oil
                    # (its section before copying) is left alone.
                    originals = [r for r in ref.rows or [] if r.get("_type") in ("data", "note")]
                    copied = [new if old.get("section") == ABSORBED_OIL_SECTION
                              else _pinches_to_tsp(_tsp_to_pinches(_water_ml_to_spoons(new)))
                              for old, new in zip(originals, copied)]
                    for row in tref.merge_rows(
                            [r for r in output_rows if r.get("template_id") == tid], copied):
                        output_rows.append(row)
                        if row.get("_type") == "data":
                            data_row_indices.append(len(output_rows) + 1)
                    continue
                except tref.TemplateReferenceError as e:
                    if strict_templates:
                        template_errors.append(f"{template_name}: {e}")
                        continue
                    LAST_TEMPLATE_WARNINGS.append(f"{template_name}: {e}")
            else:
                close = tref.near_miss(ingredient, template_index)
                if close:
                    LAST_TEMPLATE_WARNINGS.append(
                        f"{template_name}: '{ingredient}' is close to the "
                        f"template {close} but doesn't match it; matched as a food.")

            # Boiling/hot water and pasta cooking water are preparation steps,
            # not caloric ingredients â€” skip silently.
            PREP_WATER_RE = re.compile(
                r"\b(boiling|boiled|hot|warm|cold|iced|ice\s*cold)\s+water\b"
                r"|\bpasta\s+(cooking\s+)?water\b"
                r"|\bcooking\s+water\b", re.I)
            if PREP_WATER_RE.search(ingredient):
                continue

            try: qty=float(qty_raw) if qty_raw else 1.0
            except ValueError: qty=1.0

            gram_target=to_grams(qty,unit,ingredient)
            match_key = (
                ingredient.lower(),
                category.lower(),
                unit.lower(),
                bool(is_cooked),
                float(threshold),
            )
            alias_portion = None
            alias = _alias_match(ingredient, size_hint, unit)
            if alias is not None:
                food, alias_portion = alias
                score, confidence, matched_alt = 1.0, "high", None
                # The recipe layer keeps the alias's food first and fits it
                # to the line: a volume borrowed for "1/2 cup green olives"
                # (USDA has only "1 olive", 0.2 g), the cut word's portion.
                if alias_portion is None:
                    if match_key not in match_cache:
                        match_cache[match_key] = match_ingredient(
                            ingredient, boost_rules, threshold, category, unit,
                            is_cooked=is_cooked)
                    fitted = match_cache[match_key][0]
                    if fitted is not None and str(food["fdc_id"]) in (
                            str(fitted["fdc_id"]), str(fitted.get("_same_food_as"))):
                        food = fitted
            elif match_key in match_cache:
                food, score, confidence, matched_alt = match_cache[match_key]
            else:
                food, score, confidence, matched_alt = match_ingredient(
                    ingredient, boost_rules, threshold, category, unit,
                    is_cooked=is_cooked)
                match_cache[match_key] = (food, score, confidence, matched_alt)

            # Cooked pasta that ends on dry pasta ("1 cup cooked ziti": USDA
            # cooks only some shapes, see food_aliases; by weight a dry
            # product can win outright) is measured as the dry pasta it was
            # cooked from: DRY_PASTA_OZ_PER_COOKED_CUP a cup, or the cooked
            # weight over DRY_PASTA_COOKED_WEIGHT_RATIO.
            from_cooked = False
            if (_pasta_keyword(ingredient) and re.match(r"(?i)cooked\s+", ingredient)
                    and (food is None or not _is_cooked_food(food))):
                cooked_ml = _volume_to_ml(qty, unit)
                if food is None and (cooked_ml or gram_target):
                    dry = match_ingredient(re.sub(r"(?i)^cooked\s+", "", ingredient), boost_rules,
                                           threshold, category, "oz", is_cooked=False)
                    if dry[0] is not None:
                        food, score, confidence, matched_alt = dry
                if food is not None and cooked_ml:
                    qty = cooked_ml / _volume_to_ml(1.0, "cup") * DRY_PASTA_OZ_PER_COOKED_CUP
                    unit, from_cooked = "oz", True
                elif food is not None and gram_target:
                    qty = gram_target / DRY_PASTA_COOKED_WEIGHT_RATIO
                    unit, from_cooked = "g", True
                if from_cooked:
                    gram_target = to_grams(qty, unit, ingredient)

            current_excel_row=len(output_rows)+2

            if food is None:
                output_rows.append({
                    "_type":"data","_confidence":"none","_source":"none",
                    "template_id":tid,"template_name":template_name,
                    "category":category,"component_label":ingredient,
                    "notes":f"UNMATCHED (best score {score:.2f})",
                    "section":section,
                })
                data_row_indices.append(current_excel_row)
                continue

            source=food.get("source","usda")
            yield_factor=food.get("_yield_factor",None)

            # Pasta given in grams is raw â€” DB entries are cooked.
            # Apply a 2Ã— yield factor to convert raw â†’ cooked gram weight,
            # but only onto a cooked food: dry pasta (branded "LINGUINE",
            # "Pasta, dry") is weighed as it is, and so is a line that says
            # it's cooked already.
            if (yield_factor is None
                    and gram_target is not None
                    and not is_cooked
                    and _pasta_keyword(ingredient)
                    and _is_cooked_food(food)):
                yield_factor = PASTA_YIELD_FACTOR

            effective_gram_target=gram_target
            if yield_factor and gram_target is not None:
                effective_gram_target=gram_target*yield_factor

            portion=alias_portion or pick_best_portion(food,unit,effective_gram_target,qty,ingredient_for_portion,boost_rules)
            if portion is None and unit.lower() not in VOLUMETRIC_UNITS:
                portion=food["portions"][0] if food["portions"] else None
            estimated = False
            # A packet with no packet portion is measured as whatever portion
            # was picked (often one label serving); say it's an estimate.
            packet_estimate = (unit.lower() in PACKET_UNITS and not (
                portion is not None and PACKET_LABEL_RE.search(portion["label"])))
            # One packet is the label's package size ("1.4 oz/40 g"), not one
            # serving of it (tamarind soup mix: 40 g, not the 4 g serving).
            if packet_estimate and food.get("package_grams"):
                portion = {"portion_id": f"{food['fdc_id']}-pkg", "label": "1 packet",
                           "gram_weight": food["package_grams"], "gram_col": "",
                           "portion_idx": 1}
                packet_estimate = False

            u_low=unit.lower()
            is_countable=u_low in ("piece","pieces","clove","cloves","unit","units","item","serving","servings","sheet","sheets","leaf","leaves","stalk","stalks","slice","slices","strip","strips","spear","spears","head","heads","ear","ears","fillet","fillets","steak","steaks","patty","patties","chop","chops","drumstick","drumsticks","knob","knobs","cube","cubes","block","blocks","stick","sticks","wrapper","wrappers","whole","pack","sachet","sprig","sprigs","bunch","bunches")
            display_label=matched_alt if matched_alt else ingredient
            vol_mismatch=False

            if portion is None:
                portion_id=f"{food['fdc_id']}-0"
                portion_desc="100g"
                # cal_formula is per-100g; portion_amt must be in 100g units.
                portion_amt=effective_gram_target / 100 if effective_gram_target is not None else qty
                # A volume line on a food with no serving at all: its grams.
                if effective_gram_target is None and _volume_to_ml(qty, unit) is not None:
                    portion_amt = _volume_to_ml(qty, unit) * (food.get("_g_per_ml") or 1.0) / 100
                    estimated = True
                cal_formula=round(food.get("energy_kcal", 0.0), 1)
            else:
                portion_id=portion["portion_id"]
                portion_desc=f"{portion['label']} ({portion['gram_weight']:.0f} g)"

                if source=="usda":
                    gcol=portion["gram_col"]
                    food_row=food["row"]
                    cal_formula=round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                elif source == "branded":
                    # energy_kcal is calories_100g, as for USDA foods.
                    food_row=food["row"]
                    cal_formula=round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                else:
                    sheet="foods"
                    food_row=food["row"]
                    if portion.get("portion_idx",0)==0:
                        cal_formula=round(food.get("energy_kcal", 0.0), 1)
                    else:
                        cal_formula=round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

                label_unit = _portion_label_unit(portion["label"])
                if is_countable or not unit or portion.get("_cube_match"):
                    # A weight label's number counts ounces or grams, not
                    # pieces: one piece against "4 oz" is one 4 oz portion,
                    # not a quarter of it.
                    if (portion.get("_cube_match") or u_low in ("serving", "servings")
                            or WEIGHT_PORTION_LABEL_RE.match(portion["label"])):
                        portion_amt = qty
                    else:
                        serving_qty = _portion_label_qty(portion["label"])
                        portion_amt = qty / serving_qty
                elif label_unit in VOLUME_TO_TSP:
                    # If the chosen serving is volumetric (ml/cup/tbsp/tsp),
                    # prefer a volume-to-volume ratio even when the recipe
                    # quantity has already been normalized to grams.
                    recipe_ml = _volume_to_ml(qty, unit)
                    serving_qty, serving_unit = _portion_label_volume_qty(portion["label"])
                    serving_ml = _volume_to_ml(serving_qty, serving_unit or label_unit)
                    if recipe_ml is not None and serving_ml is not None and serving_ml > 0:
                        portion_amt = recipe_ml / serving_ml
                    elif effective_gram_target is not None:
                        portion_amt = effective_gram_target / portion["gram_weight"]
                    else:
                        recipe_tsp = _volume_to_tsp(qty, unit)
                        serving_tsp = _volume_to_tsp(serving_qty, serving_unit or label_unit)
                        if recipe_tsp is not None and serving_tsp is not None and serving_tsp > 0:
                            portion_amt = recipe_tsp / serving_tsp
                        else:
                            portion_amt, estimated = _mismatch_amount(qty, unit, portion, food.get("_g_per_ml"))
                            vol_mismatch = not estimated
                elif effective_gram_target is not None:
                    # Weight/ml input â€” always reliable to divide by gram_weight.
                    portion_amt = effective_gram_target / portion["gram_weight"]
                else:
                    # Volumetric input (tbsp, tsp, cup, etc.) â€” compare on a
                    # common liquid base (milliliters) so 2 cups against a
                    # 240 ml serving uses the direct 473/240 ratio.
                    recipe_ml = _volume_to_ml(qty, unit)
                    serving_qty, serving_unit = _portion_label_volume_qty(portion["label"])
                    serving_ml = _volume_to_ml(serving_qty, serving_unit or "")
                    if recipe_ml is not None and serving_ml is not None and serving_ml > 0:
                        portion_amt = recipe_ml / serving_ml
                    else:
                        # Fall back to teaspoon conversion when the serving
                        # label uses an unusual volumetric unit.
                        recipe_tsp = _volume_to_tsp(qty, unit)
                        serving_tsp = _volume_to_tsp(serving_qty, serving_unit or "")
                        if recipe_tsp is not None and serving_tsp is not None and serving_tsp > 0:
                            portion_amt = recipe_tsp / serving_tsp
                        else:
                            # Unit mismatch â€” flag
                            portion_amt, estimated = _mismatch_amount(qty, unit, portion, food.get("_g_per_ml"))
                            vol_mismatch = not estimated

            # Spoons for fine foods that only have a cup portion.
            if (portion is not None and source == "usda" and not is_countable
                    and not vol_mismatch and portion_amt > 0):
                spoon = _derived_spoon_portion(food, portion, portion_amt, unit)
                if spoon:
                    recipe_grams = portion_amt * portion["gram_weight"]
                    portion = spoon
                    portion_id = spoon["portion_id"]
                    # One decimal: a teaspoon is often under 3 g.
                    portion_desc = f"{spoon['label']} ({spoon['gram_weight']:.1f} g)"
                    portion_amt = recipe_grams / spoon["gram_weight"]
                    cal_formula = round((spoon["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                else:
                    # Cups for a cup measure of a food that has only spoons.
                    cup = _cup_portion_for_spoon(food, portion, portion_amt, unit)
                    if cup:
                        recipe_grams = portion_amt * portion["gram_weight"]
                        portion = cup
                        portion_id = cup["portion_id"]
                        portion_desc = f"{cup['label']} ({cup['gram_weight']:.0f} g)"
                        portion_amt = recipe_grams / cup["gram_weight"]
                        cal_formula = round((cup["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

            # Other volumes in the recipe's own unit ("1 cup water", not 8 fl oz).
            if (portion is not None and source == "usda" and not is_countable
                    and not vol_mismatch and portion_amt > 0):
                own = _recipe_unit_volume_portion(food, portion, unit)
                if own:
                    recipe_grams = portion_amt * portion["gram_weight"]
                    portion = own
                    portion_id = own["portion_id"]
                    portion_desc = f"{own['label']} ({own['gram_weight']:.1f} g)"
                    if own.get("_cup_as_ml"):
                        # "1 cup water" is 250 ml, not a US cup's 236.6.
                        ml = _volume_to_ml(qty, unit) / _volume_to_ml(1.0, "cup") * WATER_ML_PER_CUP
                        portion_amt = ml * _volume_to_ml(1.0, "ml") / _volume_to_ml(
                            *_portion_label_volume_qty(own["label"]))
                    else:
                        portion_amt = recipe_grams / own["gram_weight"]
                    cal_formula = round((own["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

            # Branded spoon servings, in the recipe's spoon or cup.
            if (portion is not None and source == "branded" and not is_countable
                    and not vol_mismatch and portion_amt > 0):
                recipe_grams = portion_amt * portion["gram_weight"]
                spoon = _branded_spoon_portion(portion, unit, recipe_grams)
                if spoon:
                    portion = spoon
                    portion_id = spoon["portion_id"]
                    portion_desc = f"{spoon['label']} ({spoon['gram_weight']:.1f} g)"
                    portion_amt = recipe_grams / spoon["gram_weight"]
                    cal_formula = round((spoon["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

            #â”€â”€ Portion sanity check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # If portion_amt is suspiciously small (<0.1) or large (>10),
            # compute recipe_grams and find the portion whose gram_weight is
            # closest â€” that's a better fit than the original selection.
            # Skip for countable items and the 100g-basis path (portion is None).
            # A portion in the recipe's own unit, or the spoon just worked out
            # for it, is exact, so 12 tbsp stays 12 tbsp (1 gallon against a
            # fl oz portion still moves); the 100g basis is never a better fit.
            in_recipe_unit = portion is not None and (
                portion.get("_derived_spoon")
                or (_normalise_volume_unit(unit) is not None
                    and _portion_label_unit(portion["label"]) == _normalise_volume_unit(unit)))
            if (portion is not None and not is_countable
                    and not vol_mismatch and not in_recipe_unit
                    and (portion_amt < 0.1 or portion_amt > 10)):
                recipe_grams = portion_amt * portion["gram_weight"]
                all_portions = [p for p in food.get("portions", [])
                                if p.get("portion_idx", 0) != 0]
                if all_portions:
                    better = min(all_portions,
                                 key=lambda p: abs(p["gram_weight"] - recipe_grams))
                    if better["portion_id"] != portion["portion_id"]:
                        portion = better
                        portion_id   = portion["portion_id"]
                        portion_desc = f"{portion['label']} ({portion['gram_weight']:.0f} g)"
                        portion_amt  = recipe_grams / portion["gram_weight"]
                        if source in ("usda", "branded"):
                            cal_formula = round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                        else:
                            if portion.get("portion_idx", 0) == 0:
                                cal_formula = round(food.get("energy_kcal", 0.0), 1)
                            else:
                                cal_formula = round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

            # Same kind of unit as the recipe: an exact ratio, not through
            # grams; weight lines in ounces; tiny volumes a unit smaller.
            # Absorbed oil is worked out elsewhere and left alone.
            if (not is_countable and not vol_mismatch and not estimated
                    and section != ABSORBED_OIL_SECTION
                    and not (portion is not None and portion.get("_cube_match"))):
                exact = exact_same_kind_amount(food, portion, qty, unit, yield_factor)
                if exact:
                    exact_portion, portion_amt = exact
                    if exact_portion is not portion:
                        portion = exact_portion
                        portion_id = portion["portion_id"]
                        portion_desc = f"{portion['label']} ({portion['gram_weight']:.1f} g)"
                        cal_formula = _unit_calories(portion, food)

            # A weight bought with bone, head or shell: only its edible
            # share is food (EDIBLE_SHARE). Counts are edible already.
            bone_tag = ""
            edible = _edible_share(food, as_bought)
            if edible is not None and section != ABSORBED_OIL_SECTION:
                share, what, source = edible
                portion_amt *= share
                bone_tag = f" [{what} {1 - share:.0%} left out, {source}]"

            cal_tot_formula=round(cal_formula * portion_amt, 1) if isinstance(cal_formula, float) else ""
            source_tag=" [BRANDED]" if source=="branded" else ""
            if alias is not None:
                source_tag += " [ALIAS]"
            if from_cooked:
                source_tag += " [DRY, from cooked]"
            if food.get("_respelled"):
                source_tag += f" [as \"{food['_respelled']}\"]"
            if food.get("_density_from") and portion is not None and str(
                    portion.get("portion_id", "")).startswith(f"{food['fdc_id']}-vol-"):
                source_tag += f" [portion from {food['_density_from']}]"
            if estimated and food.get("_g_per_ml"):
                source_tag += f" [{food['_g_per_ml']:.2f} g/ml from {food['_density_from']}]"
            yield_tag=(f" [yield {yield_factor}]" if yield_factor else "") + bone_tag
            vol_note = "VOL UNIT MISMATCH (3 tsp=1 tbsp, 16 tbsp=1 cup) " if vol_mismatch else ""
            if estimated and food.get("_g_per_ml"):
                vol_note += "NO VOLUME PORTION, its own serving by a relative's density "
            elif estimated:
                vol_note += "NO VOLUME PORTION, its own serving at 1 g/ml "
            elif packet_estimate:
                vol_note += "PACKET PORTION NOT FOUND, estimated "
                estimated = True
            # A line the portion doesn't measure is a guess: light red, and
            # listed at the end of the batch run, so it is fixed (a portion
            # rule, a pin, a reworded line) before import.
            unmeasured = _unmeasured_reason(portion, unit, is_countable, vol_mismatch,
                                            estimated, section)
            if unmeasured:
                confidence = "low"
                vol_note = f"CHECK AMOUNT: {unmeasured}. " + vol_note
            note_text=f"{vol_note}{'LOW CONF ' if confidence=='low' and not unmeasured else ''}score {score:.2f}{source_tag}{yield_tag}"

            output_rows.append({
                "_type":"data","_confidence":confidence,"_source":source,
                "template_id":tid,"template_name":template_name,"other_names":other_names,
                "category":category,"component_label":display_label,
                "matched_food_name":food.get("display_name",""),
                "food_id":food["fdc_id"],"portion_id":portion_id,
                "portion_amt":portion_amt,"portion_description":portion_desc,
                "calories_kcal":cal_formula,"cal_tot":cal_tot_formula,
                "sub_template_id":"","notes":note_text,
                "section":section,
                # The unit the recipe itself used ("tbsp"), for the app to
                # start the wheel on it; ml for a cup of water, which is
                # 250 ml rather than a cup.
                "recipe_unit":"ml" if portion is not None and portion.get("_cup_as_ml") else unit,
                # No portion could measure the line; it is 1 g/ml.
                "estimated":estimated,
                "unit_label": portion["label"] if portion is not None else "100 g",
                "_unit_display": portion.get("_display") if portion is not None else None,
                # A pinch row's teaspoon, for copies that come back to it.
                "_tsp_label": portion.get("_tsp_label", "") if portion is not None else "",
                "_tsp_qty": portion.get("_tsp_qty", "") if portion is not None else "",
                "unit_grams": portion["gram_weight"] if portion is not None else 100.0,
                "fry_type": fry_type or "",
                "_unmeasured": unmeasured,
            })
            data_row_indices.append(current_excel_row)
            kind = _fried_kind(ingredient)
            if kind:
                row = output_rows[-1]
                row["_fried_kind"] = kind
                # The oil rates are a share of the fried food's edible weight,
                # as its calories are: per 100 g of raw food (fry_types,
                # ABSORPTION_SOURCES.md), never the bone (28 Oct 2026).
                row["_fried_grams"] = portion_amt * (
                    portion["gram_weight"] if portion is not None else 100.0)
                fried.append(row)

        first = ing_rows[0]
        for row in output_rows:
            if row.get("template_id") == tid and row.get("_type") in ("data", "note"):
                row.setdefault("other_names", other_names)
                row["servings"] = _float_or_none(first.get("servings")) or 1.0
                row["serving_qty"] = _float_or_none(first.get("serving_qty")) or ""
                row["serving_unit"] = (first.get("serving_unit") or "").strip()
        processed.add(tid)

        if data_row_indices:
            output_rows.append({
                "_type":"subtotal","template_id":tid,
                "start_row":data_row_indices[0],"end_row":data_row_indices[-1],
            })

    sys.stderr.write("\r" + " " * 80 + "\r")  # clear progress bar
    sys.stderr.flush()
    if template_errors:
        raise tref.TemplateReferenceError(
            "Base template lines that can't be used:\n  " + "\n  ".join(template_errors))
    return [_with_display_unit(row) for row in output_rows]


# Labels that measure a container, not a piece of the food: "1 can" anchovy.
CONTAINER_LABEL_RE = re.compile(
    r"\b(?:cans?|jars?|bottles?|box(?:es)?|containers?|cartons?|tubs?|bags?)\b", re.IGNORECASE)


def _unmeasured_reason(portion, unit: str, is_countable: bool, vol_mismatch: bool,
                       estimated: bool, section: str) -> str:
    """
    Why a row's amount isn't measured, or "": no volume portion
    (VOL UNIT MISMATCH), a 1 g/ml or packet estimate, or a count line ("8
    leaf sage") measured by a volume or a container. 22 Oct 2026: these
    were only notes, and "5 anchovy fillet" went in as 5 cans.
    """
    if section == ABSORBED_OIL_SECTION:
        return ""
    if vol_mismatch:
        return f"no {unit} portion"
    if estimated:
        return "no portion in the recipe's unit, estimated"
    if portion is None:
        return "" if _unit_kind(unit) else f"no {unit or 'piece'} portion"
    u = unit.lower()
    if (is_countable or not u) and u not in PACKET_UNITS and u not in ("serving", "servings") and (
            _portion_label_unit(portion.get("label", "")) in VOLUME_TO_TSP
            or CONTAINER_LABEL_RE.search(portion.get("label", ""))
            or UNMEASURABLE_PORTION_RE.search(portion.get("label", ""))):
        return f"no {unit} portion, measured by '{portion['label']}'"
    return ""


def _with_display_unit(row: dict) -> dict:
    """[row] with its USDA unit under the display name ("1 medium" for
    'medium (4-1/8" long)'), once matching is done: the unit maths above
    read the raw label. A unit the matcher made (a pinch, 1 tsp from a
    cup) keeps its own label."""
    display = row.get("_unit_display")
    if row.get("_type") != "data" or not display or row.get("unit_label") != display[0]:
        return row
    return {**row, "unit_label": display[1]}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CLI
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def main():
    p=argparse.ArgumentParser(description="Match recipe ingredients against USDA (Supabase).")
    p.add_argument("--recipes",   default="recipes.csv")
    p.add_argument("--boosts",    default="boosts.json")
    p.add_argument("--output",    default="templates_output.xlsx")
    p.add_argument("--threshold", default=0.45, type=float)
    p.add_argument("--forceall",  action="store_true",
                   help="Skip loading existing output — overwrite everything from scratch")
    args=p.parse_args()

    script_dir = Path(__file__).resolve().parent

    def resolve_path(path: str, prefer_script_dir: bool = True) -> str:
        pth = Path(path)
        if pth.is_absolute():
            return str(pth)
        script_candidate = script_dir / pth
        cwd_candidate = Path.cwd() / pth
        candidates = (script_candidate, cwd_candidate) if prefer_script_dir else (cwd_candidate, script_candidate)
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return str(script_candidate)

    args.boosts  = resolve_path(args.boosts, prefer_script_dir=True)
    args.recipes = resolve_path(args.recipes, prefer_script_dir=False)
    args.output  = resolve_path(args.output, prefer_script_dir=False)

    if not supabase_is_configured():
        print("[!] Supabase not configured. Set SUPABASE_ANON_KEY.")
        sys.exit(1)
    print(f"[→] Per-ingredient search mode (queries Supabase per ingredient)")

    print(f"[→] Loading boost rules: {args.boosts}")
    boost_rules=load_boosts(args.boosts)
    print(f"    {len(boost_rules)} rules ({len(BUILTIN_BOOSTS)} built-in).")

    xlsx_path = args.output if args.output.endswith(".xlsx") else args.output.replace(".csv",".xlsx")
    csv_path  = xlsx_path.replace(".xlsx",".csv")

    if args.forceall:
        print(f"[→] --forceall active — skipping existing output, fresh write.")
        existing_rows = []
    else:
        print(f"[→] Loading existing output for merge: {xlsx_path}")
        existing_rows = load_existing_xlsx(xlsx_path)
        if existing_rows:
            print(f"    {len(existing_rows)} existing rows loaded.")
        else:
            print(f"    No existing file — fresh write.")

    print(f"[→] Processing recipes: {args.recipes}")
    # A failed lookup would otherwise count as no results and quietly change
    # amounts; stop before anything is written and let the run be repeated.
    fail_on_request_errors()
    try:
        new_rows=build_output_rows(args.recipes, boost_rules, args.threshold,
                                   existing_rows=existing_rows)
    except SupabaseLookupError as e:
        print(f"\n[!] {e}", file=sys.stderr)
        print("[!] Stopped; the output files were not changed. Run it again.",
              file=sys.stderr)
        sys.exit(1)

    output_rows = merge_output_rows(existing_rows, new_rows)
    new_tids = {r.get("template_id","") for r in new_rows}
    if existing_rows:
        print(f"    Replacing templates: {sorted(new_tids)}")

    data_rows=[r for r in output_rows if r.get("_type")=="data"]
    new_data  =[r for r in new_rows    if r.get("_type")=="data"]
    usda_hi=[r for r in new_data if r.get("_source")=="usda"    and r.get("_confidence")=="high"]
    usda_lo=[r for r in new_data if r.get("_source")=="usda"    and r.get("_confidence")=="low"]
    brd_hi =[r for r in new_data if r.get("_source")=="branded" and r.get("_confidence")=="high"]
    brd_lo =[r for r in new_data if r.get("_source")=="branded" and r.get("_confidence")=="low"]
    unmatched=[r for r in new_data if r.get("_confidence")=="none"]
    unmeasured=[r for r in new_data if r.get("_unmeasured")]
    print(f"    This run: {len(new_data)} ingredients  |  "
          f"USDA: {len(usda_hi)} high / {len(usda_lo)} low  |  "
          f"Branded: {len(brd_hi)} high / {len(brd_lo)} low  |  "
          f"unmatched: {len(unmatched)}  |  amount to check: {len(unmeasured)}")
    for r in unmeasured:
        print(f"      CHECK {r.get('template_name')}: {r.get('component_label')} -> "
              f"{r.get('matched_food_name')} ({r['_unmeasured']})")
    print(f"    Total in output: {len(data_rows)} ingredients across all templates.")

    print(f"[→] Writing output: {xlsx_path}")
    if HAS_OPENPYXL:
        write_xlsx(output_rows, xlsx_path)
    else:
        print(f"[!] openpyxl unavailable — skipping xlsx.")
    write_csv(output_rows, csv_path)

if __name__=="__main__":
    main()
