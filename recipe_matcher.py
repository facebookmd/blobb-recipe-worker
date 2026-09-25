#!/usr/bin/env python3
from __future__ import annotations
"""
recipe_matcher.py
-----------------
Matches recipe ingredients against the USDA food database (via Supabase)
using bigram similarity.

Usage:
    python recipe_matcher.py --recipes recipes.csv \
        [--boosts boosts.json] [--output templates_output.xlsx] \
        [--threshold 0.45]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from collections import defaultdict

from supabase_food_source import (
    is_configured as supabase_is_configured,
    search_foods as supabase_search_foods,
    load_portions_for_food_ids,
)

# â”€â”€ built-in boost rules â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BUILTIN_BOOSTS = [
    {"trigger": "soy sauce",      "boost": "shoyu soy sauce",             "weight": 0.9, "category": "japanese"},
    {"trigger": "curry roux",      "boost": "GOLDEN CURRY",                "weight": 0.9, "category": "japanese"},
    {"trigger": "cooking oil",   "boost": "vegetable oil soybean",       "weight": 0.6},
    {"trigger": "oil",           "boost": "vegetable oil soybean",       "weight": 0.6,
     "exclude": ["sesame","olive","coconut","canola","vegetable","cooking",
                 "chili","fish","palm","sunflower","peanut","avocado","truffle","infused"]},
    {"trigger": "potato",        "boost": "potatoes flesh and skin raw", "weight": 0.6,
     "exclude": ["potato starch"]},
    {"trigger": "bell pepper",   "boost": "sweet red pepper raw",        "weight": 0.6},
    {"trigger": "green peas",    "boost": "peas green frozen unprepared","weight": 0.6},
    {"trigger": "spring onion",  "boost": "scallions raw",               "weight": 0.9},
    {"trigger": "green onion",   "boost": "scallions raw",               "weight": 0.9},
    {"trigger": "scallion",      "boost": "scallions raw",               "weight": 0.9},
    {"trigger": "scallions",     "boost": "scallions raw",               "weight": 0.9},
    {"trigger": "onion",         "boost": "onions raw",                  "weight": 0.6},
    {"trigger": "garlic chives", "boost": "chives raw",                  "weight": 0.9},
    {"trigger": "garlic",        "boost": "garlic raw",                  "weight": 0.6,
     "exclude": ["garlic chives"]},
    {"trigger": "bay leaf",      "boost": "bay leaf",                    "weight": 0.6},
    {"trigger": "chili pepper",  "boost": "hot red chili pepper",        "weight": 0.6},
    {"trigger": "chilli",        "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chillies",      "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chilis",        "boost": "hot red chili pepper",        "weight": 0.8},
    {"trigger": "chili",         "boost": "hot red chili pepper",        "weight": 0.8,
     "exclude": ["powder","seasoning","sauce","oil","paste","flakes","con carne"]},
    {"trigger": "beef broth",    "boost": "beef broth canned",           "weight": 0.6},
    {"trigger": "chicken broth", "boost": "chicken broth low sodium",    "weight": 0.6},
    {"trigger": "tomato sauce",  "boost": "tomato sauce canned",         "weight": 0.6},
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
    {"trigger": "salt",          "boost": "salt table",                  "weight": 0.8,
     "exclude": ["unsalted","no salt","without salt","low salt","less salt","salted"]},
    {"trigger": "unsalted butter","boost": "butter unsalted",            "weight": 0.9},
    {"trigger": "whole-egg mayo", "boost": "mayonnaise",                 "weight": 0.9},
    {"trigger": "whole egg mayo", "boost": "mayonnaise",                 "weight": 0.9},
    {"trigger": "whole-egg mayonnaise","boost": "mayonnaise",            "weight": 0.9},
    {"trigger": "whole egg mayonnaise","boost": "mayonnaise",            "weight": 0.9},
    {"trigger": "butter",        "boost": "butter salted",               "weight": 0.7,
     "exclude": ["unsalted","peanut","almond","cashew","sunflower","cocoa","shea"]},
    {"trigger": "coriander",     "boost": "cilantro raw",                "weight": 0.8,
     "exclude": ["ground","dried","seed","seeds","powder","spice"]},
    {"trigger": "ground coriander","boost": "coriander seed",            "weight": 0.9},
    {"trigger": "coriander seed", "boost": "coriander seed",             "weight": 0.9},
    # Spice/herb boosts â€” single-word names score low against USDA's
    # "X, ground" / "X, dried" convention; boost to the expected form.
    {"trigger": "nutmeg",        "boost": "nutmeg ground",               "weight": 0.9},
    {"trigger": "turmeric",      "boost": "turmeric ground",             "weight": 0.9},
    {"trigger": "cinnamon",      "boost": "cinnamon ground",             "weight": 0.9},
    {"trigger": "allspice",      "boost": "allspice ground",             "weight": 0.9},
    {"trigger": "ginger",        "boost": "ginger root",                "weight": 0.9,
     "exclude": ["ground","dried","powder","ale","beer","snap","bread"]},
    {"trigger": "cloves",        "boost": "cloves ground",               "weight": 0.9},
    {"trigger": "clove",         "boost": "cloves ground",               "weight": 0.9},
    {"trigger": "oregano",       "boost": "oregano dried",               "weight": 0.9},
    {"trigger": "thyme",         "boost": "thyme dried",                 "weight": 0.9},
    {"trigger": "rosemary",      "boost": "rosemary fresh",              "weight": 0.9},
    {"trigger": "cayenne",       "boost": "cayenne pepper",              "weight": 0.9},
    {"trigger": "cumin",         "boost": "cumin seed",                  "weight": 0.9},
    {"trigger": "daikon",        "boost": "daikon radish",               "weight": 0.9},
    {"trigger": "flour",         "boost": "all-purpose flour",           "weight": 0.8,
     "exclude": ["rice","corn","almond","coconut","oat","bread","cake","self","rye",
                 "buckwheat","whole","00","arrowroot","tapioca","chickpea","cassava"]},
    {"trigger": "yakisoba noodles", "fdc_id": "B_2027673", "weight": 0.95},
    {"trigger": "spaghetti",     "boost": "spaghetti pasta",             "weight": 0.9,
     "exclude": ["squash"]},
    {"trigger": "white bread",   "boost": "White bread",                 "weight": 0.9,
     "exclude": ["crumb","stuffing","pudding"]},
    {"trigger": "shrimp",        "boost": "shrimp raw",                  "weight": 0.9,
     "exclude": ["paste","sauce","fried","breaded","dried","canned","surimi","powder"]},
    {"trigger": "salmon",        "boost": "salmon raw",                  "weight": 0.9,
     "exclude": ["smoked","canned","oil","sauce","burger","cake","loaf","cream"]},
    {"trigger": "large egg",     "boost": "whole egg large",             "weight": 0.9},
    {"trigger": "egg yolk",      "boost": "egg yolk large",              "weight": 0.9},
    {"trigger": "egg",           "boost": "egg raw fresh",               "weight": 0.9,
     "exclude": ["yolk", "white", "noodle", "pasta", "roll", "mayo", "mayonnaise",
                 "eggplant", "custard", "tofu", "sponge", "waffle", "roe"]},
    # Japanese cooking essentials — short names with no USDA standard entry;
    # boost to the branded/common name so the token index finds them.
    {"trigger": "mirin",         "boost": "mirin sweet rice wine",       "weight": 0.9,
     "exclude": ["vinegar"]},
    {"trigger": "sake",          "boost": "sake rice wine",              "weight": 0.9,
     "exclude": ["vinegar","salmon"]},
    {"trigger": "dashi",         "boost": "dashi stock",                 "weight": 0.8,
     "exclude": ["no dashi"]},
    {"trigger": "katsuobushi",   "boost": "bonito flakes",               "weight": 0.9},
    {"trigger": "bonito flakes", "boost": "bonito flakes dried",         "weight": 0.9},
    {"trigger": "kombu",         "boost": "kelp kombu",                  "weight": 0.9},
    {"trigger": "ponzu",         "boost": "ponzu sauce",                 "weight": 0.9},
    {"trigger": "furikake",      "boost": "furikake seasoning",          "weight": 0.9},
    {"trigger": "panko",         "boost": "panko breadcrumbs",           "weight": 0.9},
    {"trigger": "nori",          "boost": "seaweed nori",                "weight": 0.9,
     "exclude": ["furikake"]},
    {"trigger": "miso",          "boost": "miso paste",                  "weight": 0.9,
     "exclude": ["soup"]},
    {"trigger": "togarashi",     "boost": "shichimi togarashi",          "weight": 0.9},
]
PREP_WORDS = {
    "chopped","sliced","diced","minced","frozen","raw","fresh","cooked","boiled","mashed",
    "fried","grilled","roasted","baked","dried","ground","shredded","grated",
    "peeled","ripe","unripe","blanched","seasoned","sauteed","sauted","squeezed",
    "boneless","skinless","lean","extra","finely","roughly","thinly",
}

# Additional filler words present in USDA vegetable names but not ingredient
# names â€” used only for core-stripped vegetable rescoring (not strip_prep).
# "whole" is kept here (not in PREP_WORDS) so it's stripped for veg core-scoring
# but preserved in the general search string â€” important for names like
# "Whole egg, large" and "Whole milk" where "whole" is semantically meaningful.
# Additional filler words present in USDA vegetable names but not ingredient
# names â€” used only for core-stripped vegetable rescoring (not strip_prep).
# "whole" is kept here (not in PREP_WORDS) so it's stripped for veg core-scoring
# but preserved in the general search string â€” important for names like
# "Whole egg, large" and "Whole milk" where "whole" is semantically meaningful.
VEG_FILLER = PREP_WORDS | {
    "whole","with","without","and","or","from","peel","skin","bone","unprepared",
    "prepared","drained","year","round","average","type","ns","as","purchased",
}

VEG_CATEGORY = "Vegetables and Vegetable Products"

# Ingredient contains these words â†’ it's a processed product, not a raw
# vegetable. Veg core-scoring is skipped so "crispy fried shallots" doesn't
# collapse to raw shallots.
PROCESSED_MARKERS_RE = re.compile(
    r"\b(crispy|crunchy|fried|deep.fried|battered|breaded|pickled|fermented|"
    r"dried|dehydrated|candied|glazed|roasted|toasted)\b", re.I
)

def _core(text):
    """Strip USDA filler words and normalise â€” used for vegetable rescoring."""
    tokens = re.split(r"[\s,/\-]+", normalise(text))
    kept = [t for t in tokens if t and t not in VEG_FILLER]
    return " ".join(kept) if kept else normalise(text)


PORTION_UNIT_KEYWORDS = {
    # Volumetric
    "tbsp":["tablespoon","tbsp"],"tablespoon":["tablespoon","tbsp"],
    "tsp":["teaspoon","tsp"],"teaspoon":["teaspoon","tsp"],
    "cup":["cup"],"cups":["cup"],
    # Weight
    "oz":["ounce","oz"],"lb":["pound","lb"],"g":["gram","100g","100 g"],
    # Countable â€” generic
    "piece":["medium","large","small","piece","unit","wrapper","wrappers","whole"],
    "clove":["clove"],
    "slice":["slice"],
    "can":["can"],
    # Countable â€” shape/cut
    "stick":["stick"],
    "strip":["strip","strips"],
    "leaf":["leaf","leaves"],
    "spear":["spear"],
    "head":["head"],
    "ear":["ear"],
    "fillet":["fillet"],
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

def bigrams(text):
    t = text.lower()
    return {t[i:i+2] for i in range(len(t)-1)}

def bigram_similarity(a, b):
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return 2*len(ba&bb)/(len(ba)+len(bb))


def _ordered_query_tokens(query_tokens, index):
    """Process rarer query tokens first so broad terms cannot crowd out
    specific hits when candidate lists are truncated."""
    return sorted(query_tokens, key=lambda tok: (len(index.get(tok, [])), tok))

def _exact_label_bonus(search: str, label: str) -> float:
    """
    Give a strong boost when the query matches the label exactly or as a
    contiguous phrase. This keeps exact labels ahead of broader token matches.
    """
    s = normalise(search)
    l = normalise(label)
    if not s or not l:
        return 0.0
    s_tokens = [_canonical_token(t) for t in s.split()]
    l_tokens = [_canonical_token(t) for t in l.split()]
    if s_tokens and l_tokens and len(s_tokens) <= 3 and sorted(s_tokens) == sorted(l_tokens):
        return 0.52 if len(s_tokens) <= 2 else 0.44
    if s == l:
        return 0.45
    if l.startswith(s + " ") or l.startswith(s + ",") or l.startswith(s + " -"):
        return 0.25
    if len(s.split()) == 1 and re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", l):
        return 0.08
    return 0.0


def _label_prefix_bonus(search: str, label: str) -> float:
    """
    Small bonus when the front label starts with the query phrase.
    This helps exact front labels beat broader same-head candidates.
    """
    s = normalise(search)
    l = normalise(label)
    if not s or not l:
        return 0.0
    if l == s:
        return 0.35
    if l.startswith(s + " ") or l.startswith(s + ",") or l.startswith(s + " -"):
        return 0.2
    return 0.0


def _exact_label_priority(search: str, label: str) -> float:
    """
    Hard preference for a normalized exact label match.

    This is used in the USDA and branded scorers so a true exact match
    always stays ahead of broader variants that happen to contain the same
    head word.
    """
    return 1.0 if normalise(search) == normalise(label) else 0.0


def _contiguous_phrase_bonus(search: str, label: str) -> float:
    """
    Reward labels that contain the full query as one contiguous phrase.
    This is stronger than scattered token overlap because it preserves the
    actual phrase order, not just the same words somewhere in the line.
    """
    s_tokens = normalise(search).split()
    l = normalise(label)
    if len(s_tokens) <= 1 or not l:
        return 0.0
    s = " ".join(s_tokens)
    if not s:
        return 0.0
    if s == l:
        return 0.5
    if re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", l):
        return 0.35
    return 0.0


def _extra_token_penalty(search: str, label: str) -> float:
    """
    Penalize candidate labels as they accumulate words that are not part of
    the query phrase. This pushes shorter exact phrase hits ahead of long
    descriptions that merely contain the same ingredients somewhere.
    """
    s_tokens = normalise(search).split()
    l_tokens = normalise(label).split()
    if not s_tokens or not l_tokens:
        return 0.0
    s_canon = {_canonical_token(tok) for tok in s_tokens}
    l_canon = [_canonical_token(tok) for tok in l_tokens]
    extra = sum(1 for tok in l_canon if tok not in s_canon)
    if extra <= 0:
        return 0.0
    # Allow neutral suffix words to stay relatively close for simple labels
    # like "white rice, raw" while still penalizing long descriptive titles.
    neutral_suffix = {"raw", "fresh", "plain", "whole", "natural", "organic"}
    if len(s_tokens) == 1 and len(l_tokens) > 1 and all(tok in neutral_suffix for tok in l_tokens[1:]):
        return 0.0
    per_token = 0.06 if len(s_tokens) > 1 else 0.04
    return min(extra * per_token, 0.45)


def _front_label_match_bonus(search: str, label: str) -> float:
    """
    Give a modest bonus when a multiword query is present in order at the
    front of the label, even if the label includes extra descriptive words in
    between. This helps labels like "Koji Firm Granular Rice, Koji" win for
    "koji rice" without turning them into hard pins.
    """
    s_tokens = normalise(search).split()
    l = normalise(label)
    if len(s_tokens) <= 1 or not l:
        return 0.0
    head = s_tokens[0]
    if not l.startswith(head + " "):
        return 0.0
    l_tokens = set(l.split())
    if not all(tok in l_tokens for tok in s_tokens):
        return 0.0
    return 0.5


def _single_token_prefix_penalty(search: str, label: str) -> float:
    """
    Penalize one-word queries when the query token appears later in a label
    behind a distinctive modifier like "wasabi". This keeps plain foods ahead
    of flavored/snack variants while still allowing safe color/size modifiers
    such as "green peas" or "white rice".
    """
    s_tokens = [_canonical_token(t) for t in normalise(search).split()]
    l_tokens = [_canonical_token(t) for t in normalise(label).split()]
    if len(s_tokens) != 1 or not s_tokens or not l_tokens:
        return 0.0
    token = s_tokens[0]
    if token not in l_tokens:
        return 0.0
    idx = l_tokens.index(token)
    if idx <= 0:
        return 0.0
    prefixes = l_tokens[:idx]
    safe_prefixes = {
        "white", "brown", "black", "green", "red", "yellow",
        "short", "long", "medium", "glutinous", "plain", "raw",
        "uncooked", "dry", "fresh", "cooked", "whole", "baby",
    }
    if all(p in safe_prefixes for p in prefixes):
        return 0.0
    return 0.5 if any(p in {"wasabi", "pickled", "sushi", "spicy", "seasoned", "salted", "smoked", "roasted", "crispy", "candied"} for p in prefixes) else 0.2


def _generic_tail_penalty(search: str, label: str) -> float:
    """
    Slightly penalize matches that only agree on a generic trailing token
    like powder/sauce/broth while the head words differ.
    """
    s_tokens = normalise(search).split()
    l_tokens = normalise(label).split()
    if not s_tokens or not l_tokens:
        return 0.0
    generic_tail = {
        "powder", "powders", "sauce", "sauces", "broth", "stock",
        "paste", "oil", "oils", "extract", "extracts", "seasoning",
        "seasonings", "mix", "mixes", "blend", "blends", "flakes",
        "noodle", "noodles", "pasta",
        "muffin", "muffins", "cake", "cakes", "bread", "breads",
        "loaf", "loaves", "cookie", "cookies", "bar", "bars",
        "pastry", "pastries", "pie", "pies", "tart", "tarts",
        "donut", "donuts", "bun", "buns", "roll", "rolls",
        "cracker", "crackers", "chip", "chips", "snack", "snacks",
        "dessert", "desserts",
    }
    if len(s_tokens) == 1:
        if l_tokens[0] != s_tokens[0]:
            return 0.0
        extra_tokens = l_tokens[1:]
        if not extra_tokens:
            return 0.0
        neutral_tail = {"raw", "fresh", "uncooked", "plain", "whole", "natural"}
        if all(tok in neutral_tail for tok in extra_tokens):
            return 0.0
        if any(tok in generic_tail for tok in extra_tokens):
            return 1.10
        return 0.25
    if len(l_tokens) < 2:
        return 0.0
    if s_tokens[-1] != l_tokens[-1]:
        return 0.0
    if s_tokens[-1] not in generic_tail:
        return 0.0
    if s_tokens[0] != l_tokens[0]:
        return 0.10
    return 0.0


def _missing_query_token_penalty(search: str, label: str) -> float:
    """
    Penalize candidates that miss important query tokens.

    Multi-word ingredients are usually looking for a specific food form and a
    specific head ingredient. When a candidate misses either the anchor token
    (for example matcha/koji/strawberry) or the generic form token (powder,
    broth, flakes), it should lose against a closer label instead of winning on
    a broad bigram overlap.
    """
    s_tokens = normalise(search).split()
    l_tokens = set(normalise(label).split())
    if len(s_tokens) <= 1 or not s_tokens or not l_tokens:
        return 0.0

    anchors = _query_anchor_tokens(search)
    missing_anchors = sum(1 for tok in anchors if not _token_in_label(tok, l_tokens))
    missing_generic = sum(1 for tok in s_tokens if tok in GENERIC_QUERY_TOKENS and not _token_in_label(tok, l_tokens))

    return (0.28 * missing_anchors) + (0.18 * missing_generic)


def _head_token_mismatch_penalty(search: str, label: str) -> float:
    """
    Penalize labels that only mention the query anchor later in the name while
    starting with a different product head.

    This helps distinguish labels like "Custard Powder, Strawberry" from the
    actual front-labeled ingredient "Strawberry Powder" without harming cases
    where the anchor is already the head token (matcha powder, koji rice, etc.).
    """
    s_tokens = normalise(search).split()
    l_tokens = normalise(label).split()
    if len(s_tokens) <= 1 or not s_tokens or not l_tokens:
        return 0.0
    anchors = _query_anchor_tokens(search)
    if not anchors:
        return 0.0
    head = l_tokens[0]
    if head in anchors:
        return 0.0
    if not any(_token_in_label(tok, set(l_tokens[1:])) for tok in anchors):
        return 0.0
    return 0.32


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
    if t.endswith("es") and len(t) > 4 and not t.endswith(("ses", "xes", "zes", "ches", "shes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def _compound_prefix_penalty(search: str, label: str) -> float:
    """
    Penalize labels that start with the query but continue into a different
    food item, so plain staples beat flavored/compound variants.
    """
    s = normalise(search)
    l = normalise(label)
    if not s or not l or l == s:
        return 0.0
    if not (l.startswith(s + " ") or l.startswith(s + ",") or l.startswith(s + " -") or l.startswith(s + " &")):
        return 0.0
    extra_tokens = l[len(s):].replace(",", " ").replace("-", " ").replace("&", " ").split()
    if not extra_tokens:
        return 0.0
    neutral_suffix = {
        "raw", "fresh", "plain", "whole", "natural", "organic",
        "unsalted", "salted", "light", "lite", "low", "reduced",
        "fat", "fatfree", "fat-free",
    }
    if all(tok in neutral_suffix for tok in extra_tokens):
        return 0.0
    compound_food_tokens = {
        "apple", "pepper", "wafer", "cone", "cane", "fruit", "berry",
        "plum", "gum", "candy", "caramel", "chocolate", "cookie",
        "cracker", "chip", "snack", "dessert", "pie", "cake", "muffin",
    }
    if any(tok.rstrip("s") in compound_food_tokens for tok in extra_tokens):
        return 0.7
    return 0.15


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


def _query_anchor_tokens(search: str) -> set[str]:
    """
    Return the query tokens that should carry most of the matching weight.
    Generic food words are removed so a distinctive term like "bonito" can
    suppress unrelated candidates such as chocolate cereal flakes.
    """
    tokens = {_canonical_token(t) for t in normalise(search).split() if len(t) >= 3}
    anchors = {t for t in tokens if t not in GENERIC_QUERY_TOKENS}
    return anchors or tokens


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


def _near_token_bonus(search: str, label: str) -> float:
    """
    Give a small boost when a longer, meaningful query token is almost the
    same as a candidate token. This helps close spellings/romanizations like
    tonkatsu/tonkotsu without creating ingredient-specific rules.
    """
    s_tokens = [_canonical_token(t) for t in normalise(search).split()]
    l_tokens = [_canonical_token(t) for t in normalise(label).split()]
    if not s_tokens or not l_tokens:
        return 0.0
    bonus = 0.0
    for st in s_tokens:
        if len(st) < 5 or st in GENERIC_QUERY_TOKENS:
            continue
        if st in l_tokens:
            bonus += 0.08
            continue
        if any(len(lt) >= 5 and _one_edit_apart(st, lt) for lt in l_tokens):
            bonus += 0.12
    return min(bonus, 0.24)


def _prefix_dish_penalty(search: str, label: str) -> float:
    """
    Penalize labels that start with the query but then continue into a
    processed/dish-style tail, like "white miso soup" or "sea salt popcorn".
    This keeps the plain ingredient ahead of compound product names.
    """
    s = normalise(search)
    l = normalise(label)
    if not s or not l or l == s:
        return 0.0
    if not (l.startswith(s + " ") or l.startswith(s + ",") or l.startswith(s + " -")):
        return 0.0
    extra_tokens = l[len(s):].replace(",", " ").replace("-", " ").split()
    dish_tail = {
        "soup", "soups", "popcorn", "ramen", "noodle", "noodles", "chips", "chip",
        "crackers", "cracker", "snack", "snacks", "cereal", "bar", "bars",
        "cookie", "cookies", "cake", "cakes", "muffin", "muffins", "bread",
        "breadsticks", "flatbread", "flatbreads", "bruschette", "crisps", "crisp",
        "naan", "pita", "pitas", "stix", "straws", "bites",
        "drink", "drinks", "beverage", "beverages", "juice",
        "soda", "sauces", "sauce", "stock", "broth", "meal", "meals",
        "caramel", "candy", "candies", "chocolate", "toffee", "fudge",
        "dessert", "desserts", "sweet", "sweets", "confection", "confections",
    }
    if any(tok in dish_tail for tok in extra_tokens):
        return 0.65
    return 0.0

def strip_prep(text):
    tokens = re.split(r"[\s,/\-]+", text.lower())
    kept = [t for t in tokens if t and t not in PREP_WORDS]
    return " ".join(kept) if kept else text.lower()

def normalise(text):
    return re.sub(r"[^a-z0-9 ]"," ",text.lower()).strip()


COLOR_WORDS = {
    "red", "green", "white", "black", "brown", "yellow", "purple",
    "orange", "pink", "blue", "golden",
}

PROCESS_PRESERVE_WORDS = {
    "pickled", "fermented", "marinated", "salted", "candied", "preserved",
    "soured", "seasoned",
}


def _strip_color_words_if_process(search: str) -> str:
    """
    For preserved/prepared foods like pickled ginger or fermented radish,
    remove color words that often describe a variant rather than the food.
    """
    tokens = normalise(search).split()
    if not any(tok in PROCESS_PRESERVE_WORDS for tok in tokens):
        return search
    stripped = [tok for tok in tokens if tok not in COLOR_WORDS]
    return " ".join(stripped) if stripped else search


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


# Portion label substrings indicating yield/processing units, not serving sizes.
# Kept in portions list but deprioritised during selection.
PORTION_LABEL_BLOCKLIST = [
    "yield from",
    "excluding refuse",
    "with refuse",
    "as purchased",
    "as consumed",
    "packet",
    "sachet",
    "envelope",
]

PORTION_LABEL_IGNORE_PREFIXES = (
    "guideline amount",
    "guideline amounts",
)

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

    def get(self, fdc_id: str) -> dict | None:
        return self._by_id.get(fdc_id)

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

def _split_alt_names(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    return [a.strip().strip('"')
            for a in re.split(r'",\s*"', raw)
            if a.strip().strip('"')]


def _row_text(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


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
        label = _row_text(portion_row, "description", "label")
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

    return {
        "source": "usda",
        "row": row_index,
        "fdc_id": fdc_id,
        "display_name": display_name,
        "alt_names": alt_names,
        "category": category,
        "energy_kcal": energy_kcal,
        "is_raw": is_raw,
        "portions": portions,
    }


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
        label = _row_text(portion_row, "description", "label")
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
        })

    return {
        "source": "branded",
        "row": row_index,
        "fdc_id": f"B_{fdc_id}",
        "display_name": display_name,
        "item_name": item_name,
        "category": _row_text(row, "brand_owner", "category"),
        "energy_kcal": energy_kcal,
        "portions": portions,
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


def _search_usda_for_ingredient(query: str) -> USDAIndex:
    """Build a small USDAIndex from per-ingredient Supabase search (non-branded)."""
    return _search_and_build_index(query, source_set="usda")


def _search_branded_for_ingredient(query: str) -> USDAIndex:
    """Build a small USDAIndex from per-ingredient Supabase search (branded only)."""
    return _search_and_build_index(query, source_set="branded")


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


def _boost_match_is_too_generic(ingredient: str, trigger: str) -> bool:
    """
    Block short generic boost triggers from hijacking more specific phrases.
    This keeps matches like "pickled red ginger" from collapsing to a plain
    ginger root entry while still allowing neutral prep variants such as
    "ground ginger" or "plain rice".
    """
    ing_tokens = normalise(ingredient).split()
    trig_tokens = normalise(trigger).split()
    if len(trig_tokens) != 1 or len(ing_tokens) <= 1:
        return False
    token = trig_tokens[0]
    if token not in ing_tokens:
        return False
    idx = ing_tokens.index(token)
    if idx == 0:
        return False
    prefixes = ing_tokens[:idx]
    return any(tok not in BOOST_NEUTRAL_PREFIXES and tok not in PREP_WORDS for tok in prefixes)


def _boost_trigger_matches(ingredient: str, trigger: str) -> bool:
    """
    Match a boost trigger against an ingredient name.

    Keep the fast substring check for ordinary phrases, but also treat
    reordered descriptor pairs as equivalent so rules like "silken tofu"
    and ingredient text like "tofu, silken" resolve through the same map.
    """
    ing_norm = normalise(ingredient)
    trig_norm = normalise(trigger)
    if not ing_norm or not trig_norm:
        return False
    if trig_norm in ing_norm:
        return True

    ing_tokens = [_canonical_token(t) for t in ing_norm.split() if t]
    trig_tokens = [_canonical_token(t) for t in trig_norm.split() if t]
    if len(trig_tokens) <= 1 or len(ing_tokens) != len(trig_tokens):
        return False

def apply_boosts(ingredient, boost_rules, category=""):
    """
    Apply the first matching boost rule to ingredient.

    Rule fields:
      trigger              : substring to match in ingredient name (required)
      boost                : alternative search string (required unless portion_gram_weight)
      weight               : confidence bonus 0-1 (default 0.6)
      category             : only fire when recipe category contains this string (optional)
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
        if not _boost_trigger_matches(ingredient, rule["trigger"]):
            continue
        if _boost_match_is_too_generic(ingredient, rule["trigger"]):
            continue
        if any(ex.lower() in ing for ex in rule.get("exclude", [])):
            continue
        rule_cat = rule.get("category", "").lower()
        if rule_cat and rule_cat not in cat:
            continue
        # Portion override rules don't affect the search string
        if "portion_gram_weight" in rule and "boost" not in rule:
            continue
        if rule.get("fdc_id"):
            return ingredient, 0.0, rule["fdc_id"]
        return rule["boost"], rule.get("weight", 0.6), None
    return ingredient, 0.0, None

def get_portion_override(ingredient: str, boost_rules: list, unit: str = "") -> dict | None:
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
        if not _boost_trigger_matches(ingredient, rule["trigger"]):
            continue
        if any(ex.lower() in ing for ex in rule.get("exclude", [])):
            continue
        rule_unit = rule.get("portion_unit", "").lower().strip()
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
def _score_list(search, foods, boost_weight, boosted, is_processed=False, is_cooked=False, unit=""):
    """
    Score every food against display_name and alternate names.
    For vegetable entries, also compute a core-stripped score (both sides
    stripped of prep/filler words) and take the max â€” this prevents USDA
    names like "Cucumber, with peel, raw" from scoring low against "cucumbers"
    due to bigram dilution from filler tokens.
    Returns (best_food, best_score, matched_alt_name).
    """
    best_food, best_score, best_alt, best_food_is_raw = None, 0.0, None, False
    search_core = _core(search)
    query_tokens = [_canonical_token(t) for t in normalise(search).split()]
    single_query = len(query_tokens) == 1
    query_token = query_tokens[0] if single_query else ""
    raw_rice_request = "rice" in search and any(k in search for k in ("raw", "uncooked", "dry"))
    food_iter = foods.candidates(search) if hasattr(foods, "candidates") else foods
    for food in food_iter:
        food_tokens = [_canonical_token(t) for t in normalise(food["display_name"]).split()]
        s_display = bigram_similarity(search, normalise(food["display_name"]))
        s = s_display
        s += _exact_label_bonus(search, food["display_name"])
        s += _label_prefix_bonus(search, food["display_name"])
        s += _contiguous_phrase_bonus(search, food["display_name"])
        s += _front_label_match_bonus(search, food["display_name"])
        s -= _single_token_prefix_penalty(search, food["display_name"])
        s -= _compound_prefix_penalty(search, food["display_name"])
        s -= _prefix_dish_penalty(search, food["display_name"])
        if single_query:
            if not _token_in_label(query_token, set(food_tokens)):
                s -= 0.35
        if query_tokens and all(tok in food_tokens for tok in query_tokens):
            s += 0.18
        if len(query_tokens) > 1:
            missing = sum(1 for tok in query_tokens if tok not in food_tokens)
            if missing:
                s -= 0.24 * missing
            s -= _head_token_mismatch_penalty(search, food["display_name"])
        s -= _extra_token_penalty(search, food["display_name"])
        if unit and unit.lower() in VOLUMETRIC_UNITS and query_tokens:
            missing = sum(1 for tok in query_tokens if tok not in food_tokens)
            if missing:
                s -= 0.18 * missing
        if any(tok in PROCESS_PRESERVE_WORDS for tok in query_tokens) and any(tok in food_tokens for tok in PROCESS_PRESERVE_WORDS):
            s += 0.18
        s += _near_token_bonus(search, food["display_name"])
        s -= _generic_tail_penalty(search, food["display_name"])
        if is_cooked and "rice" in search and "cooked" in food["display_name"].lower():
            s += 0.2
        if raw_rice_request and "rice" in search:
            food_name = food["display_name"].lower()
            if "uncooked" in food_name or food.get("is_raw"):
                s += 0.8
            if "cooked" in food_name:
                s -= 0.5
        winning_alt = None
        for alt in food.get("alt_names", []):
            s_alt = bigram_similarity(search, normalise(alt))
            if s_alt > s:
                s = s_alt
                winning_alt = alt
        # For vegetables, rescore using core-stripped names and take the max.
        # Raw/cooked distinction is irrelevant for produce â€” a cucumber is a
        # cucumber regardless of "with peel, raw" in the USDA name.
        if food.get("category") == VEG_CATEGORY and not is_processed:
            # Strip size words from the search side only â€” "medium carrots"
            # should match "Carrots, raw" but size must stay in the top-level
            # search string for portion label matching downstream.
            search_veg = re.sub(r"\b(large|medium|small)\b", "", search_core).strip()
            search_veg = re.sub(r"\s+", " ", search_veg) or search_core
            s_core = bigram_similarity(search_veg, _core(food["display_name"]))
            # Prefer raw entries when scores are equal â€” "carrots" should match
            # "Carrots, raw" not "Carrots, cooked, boiled".
            if s_core > s or (s_core == s and food.get("is_raw") and not best_food_is_raw):
                s = s_core
                winning_alt = None  # core match is on display_name
        if len(query_tokens) > 1:
            s -= _missing_query_token_penalty(search, food["display_name"])
        if boosted and boost_weight:
            s = min(1.0, s + boost_weight * 0.15)
        if s > best_score or (s == best_score and food.get("is_raw") and not best_food_is_raw):
            best_score, best_food, best_alt, best_food_is_raw = s, food, winning_alt, bool(food.get("is_raw"))
    return best_food, best_score, best_alt
def _serving_unit_compat(serving, unit):
    """
    Return how well a serving label's unit matches the recipe unit.
      2 = same vol unit (tbspâ†”tbsp or tspâ†”tsp)
      1 = cross vol unit (tbspâ†”tsp â€” convertible)
      0 = no vol match (generic label or incompatible unit)
    """
    label_unit = _portion_label_unit(serving["label"])
    recipe_unit = _normalise_volume_unit(unit)
    if not label_unit or not recipe_unit:
        return 0
    if label_unit == recipe_unit:
        return 2
    if label_unit in VOLUME_TO_TSP and recipe_unit in VOLUME_TO_TSP:
        return 1
    return 0

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
        if abs(p.get("gram_weight", 100.0) - 100.0) <= 1.0:
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

# If the score falls below this, the ingredient is flagged as
# unmatched in the spreadsheet and omitted from app exports entirely.
# Reviewers should add a boost rule or manually assign a food_id.
MIN_CONFIDENCE = 0.66

# Ingredients containing these trigger strings get remapped to a cleaner
# search term before matching. Applied after boost rules.
INGREDIENT_REMAP = {
    "peppercorn":        "black pepper ground",
    "peppercorns":       "black pepper ground",
    "whole pepper":      "black pepper ground",
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
    # NOTE: bare "white rice", "jasmine rice", "basmati rice", "long grain rice"
    # are intentionally NOT remapped here â€” they are uncooked and handled by
    # boost rules pointing to the raw USDA entry (FDC 168878 raw).
}

# Direct FDC ID mapping for mince/ground meat ingredients.
# These bypass bigram matching entirely since "ground" gets stripped by strip_prep
# making them hard to match. Yield factor 0.75 â€” typical rawâ†’cooked loss for ground meat.
MINCE_IDS = {
    #  keyword    fdc_id           yield
    "pork":    ("167903",   0.75),  # Pork ground
    "beef":    ("1_171799", 0.75),  # Ground beef, pan-browned (generic)
    "chicken": ("171117",   0.75),  # Ground chicken, pan-browned
    "lamb":    ("174370",   0.75),  # Ground lamb, raw
    "turkey":  ("171505",   0.75),  # Ground turkey, raw
    "veal":    ("175290",   0.75),  # Ground veal, raw
}

CHICKEN_CUT_IDS = {
    #  keyword        (skin_on_fdc,  skinless_fdc)
    "thigh":       ("172385",  "173627"),   # thigh meat+skin raw | thigh meat only raw
    "drumstick":   ("172373",  "172376"),   # drumstick meat+skin raw | drumstick meat only raw
    "breast":      ("171474",  "171077"),   # breast meat+skin raw | breast boneless skinless raw
    "wing":        ("172390",  "172390"),   # wing meat+skin raw
}
CHICKEN_CUT_SKINLESS_TRIGGERS = {"skinless", "skin removed", "skin-off", "skin off", "no skin"}
CHICKEN_CUT_EXCLUDES = {
    "ground", "mince", "minced", "broth", "stock", "sausage",
    "nugget", "tender", "strips", "cutlet",
}

# Direct FDC ID mapping for ground/powdered spices where strip_prep removes
# "ground" from the search string causing mismatches (e.g. ginger â†’ Ginger ale).
# Triggered when ingredient contains "ground X" or "X powder".
SPICE_GROUND_IDS = {
    #  keyword     fdc_id
    "ginger":    "170926",   # Ginger, ground
    "coriander": "170922",   # Coriander seed (has alt: Coriander, ground)
}

# Direct FDC ID mapping for whole eggs â€” bigram search scores too low on the
# short string "egg" to clear MIN_CONFIDENCE, so we bypass matching entirely.
EGG_IDS = {
    "egg": "171287",   # Egg, whole, raw, fresh
}


EGG_IDS = {
    # keyword    fdc_id
    "egg yolk":  "172183",   # Egg, yolk, raw, fresh
    "egg white":  "172185",  # Egg, white, raw, fresh
    "egg":        "748967",  # Egg, whole, raw, fresh
}

SHRIMP_IDS = {
    "raw":    "174210",  # Shrimp, mixed species, raw (may contain additives)
    "cooked": "175180",  # Shrimp, cooked, dry heat
}

# Maps meat keyword â†’ (generic USDA FDC_ID, raw-to-cooked yield factor).
# Yield converts raw recipe gram weights to cooked equivalent so calories
# are accurate when matching a raw ingredient to a cooked DB entry.
# Source: USDA Agriculture Handbook No. 102 cooking yield tables.
#
# Cube portions available in these entries:
#   Pork, cooked  (1_167855) â€” 1.5" cube, 3 oz card-deck
#   Beef          (169484)   â€” 1.5" cube, 3 oz card-deck
MEAT_GENERIC_IDS = {
    #  keyword    fdc_id        yield (rawâ†’cooked)
    "pork":  ("1_167855",  0.73),   # Pork, cooked â€” ~27% moisture/fat loss
    "beef":  ("169484",    0.70),   # Beef â€” ~30% loss
    "lamb":  ("172509",    0.70),   # Lamb stew/kabob meat, lean, braised
    "veal":  ("169457",    0.74),   # Veal, composite
}

# Pre-built lookup populated at first use by _get_meat_generics()
_MEAT_GENERIC_CACHE: dict[str, tuple] = {}

def _get_meat_generics(usda_foods: list) -> dict[str, tuple]:
    """Return {meat_keyword: (food_dict, yield_factor)} for generic meat entries."""
    global _MEAT_GENERIC_CACHE
    if _MEAT_GENERIC_CACHE:
        return _MEAT_GENERIC_CACHE
    for keyword, (fdc_id, yield_factor) in MEAT_GENERIC_IDS.items():
        food = usda_foods.get(fdc_id)
        if food:
            _MEAT_GENERIC_CACHE[keyword] = (food, yield_factor)
    return _MEAT_GENERIC_CACHE

def _meat_keyword(ingredient: str) -> str | None:
    """Return the first meat keyword found in the ingredient name, or None."""
    ing = ingredient.lower()
    for kw in MEAT_GENERIC_IDS:
        if kw in ing:
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
}
PASTA_YIELD_FACTOR = 2.0

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

# Cache exact match results for repeated ingredient strings across recipe files.
_MATCH_CACHE: dict[tuple, tuple] = {}


def match_ingredient(ingredient, boost_rules=None, threshold=0.45,
                     category="", unit="", is_cooked=False):
    """
    Returns (food, score, confidence, matched_alt).
    matched_alt is the alternate name string that won the match, or None
    if the display_name won. The app should display matched_alt when set.

    Queries Supabase per-ingredient (FTS + ilike) — no bulk download.
    """
    if boost_rules is None:
        boost_rules = BUILTIN_BOOSTS

    cache_key = (
        ingredient.lower(),
        category.lower(),
        unit.lower(),
        bool(is_cooked),
        float(threshold),
    )
    cached = _MATCH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Build per-ingredient indexes from Supabase search
    search_query = normalise(strip_prep(ingredient))
    usda_foods = _search_usda_for_ingredient(search_query)
    # Branded is lazy — only fetched when USDA doesn't meet threshold
    branded_index = None
    _branded_fetched = False

    def _get_branded():
        nonlocal branded_index, _branded_fetched
        if not _branded_fetched:
            branded_index = _search_branded_for_ingredient(search_query)
            _branded_fetched = True
        return branded_index
    # â”€â”€ Mince/ground meat â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # "ground" gets stripped by strip_prep making bigram matching unreliable.
    # Detect mince keywords and map directly to the correct USDA entry.
    ing_lower = ingredient.lower()
    category_lower = category.lower()
    is_japanese_category = "japanese" in category_lower
    rice_default_cooked = False
    if _rice_keyword(ingredient) and not any(raw_kw in ing_lower for raw_kw in ("raw", "uncooked", "dry")):
        rice_default_cooked = True
        is_cooked = True
    if (unit.lower() not in VOLUMETRIC_UNITS
            and ("mince" in ing_lower or "minced" in ing_lower or "ground" in ing_lower)):
        for kw, (fdc_id, yield_factor) in MINCE_IDS.items():
            if kw in ing_lower:
                food = usda_foods.get(fdc_id)
                if food:
                    tagged = dict(food)
                    # Recipe already describes cooked weight â€” don't shrink again
                    tagged["_yield_factor"] = None if is_cooked else yield_factor
                    return tagged, 0.95, "high", None

    # â”€â”€ Ground/powdered spices â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Same strip_prep problem: "ground ginger" â†’ "ginger" â†’ matches Ginger ale.
    if "ground" in ing_lower or "powder" in ing_lower:
        for kw, fdc_id in SPICE_GROUND_IDS.items():
            if kw in ing_lower:
                food = usda_foods.get(fdc_id)
                if food:
                    return dict(food), 0.95, "high", None

    # â”€â”€ Specific chicken cuts â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if "chicken" in ing_lower and not any(ex in ing_lower for ex in CHICKEN_CUT_EXCLUDES):
        for cut_kw, (skin_on_id, skinless_id) in CHICKEN_CUT_IDS.items():
            if cut_kw in ing_lower:
                is_skinless = any(t in ing_lower for t in CHICKEN_CUT_SKINLESS_TRIGGERS)
                fdc_id = skinless_id if is_skinless else skin_on_id
                food = usda_foods.get(fdc_id)
                if food:
                    tagged = dict(food)
                    tagged["_cut_keyword"] = cut_kw  # used by pick_best_portion
                    return tagged, 0.95, "high", None
                break

    # Apply ingredient remaps first (e.g. peppercorns â†’ black pepper ground)
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
        elif is_japanese_category:
            remapped = "cooked medium grain white rice"
        else:
            remapped = "white rice long grain cooked"
    for trigger, replacement in INGREDIENT_REMAP.items():
        if trigger in ingredient.lower():
            remapped = replacement
            break

    boosted_text, boost_weight, pinned_fdc_id = apply_boosts(remapped, boost_rules, category)
    boosted = boosted_text.lower() != remapped.lower()
    search_source = boosted_text
    if "fillet" in ing_lower and _is_fish_or_seafood_name(ing_lower):
        search_source = re.sub(r"\bfillets?\b", " ", search_source, flags=re.I)
    search_raw = normalise(search_source)
    search  = normalise(strip_prep(search_source))
    cooked_stripped_source = re.sub(r"\s*,\s*cooked\b", "", search_source, flags=re.I)
    cooked_stripped_search = None
    scoring_search = search_raw if unit.lower() in VOLUMETRIC_UNITS else search
    search_match = _strip_color_words_if_process(scoring_search)
    query_tokens = normalise(search_match).split()
    is_processed = bool(PROCESSED_MARKERS_RE.search(ingredient))
    volumetric_unit = unit.lower() in VOLUMETRIC_UNITS
    search_exact = normalise(search_match)
    meat_kw = _meat_keyword(remapped)
    if "banana blossom" in search_exact:
        meat_kw = None
    # â”€â”€ Raw rice lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if "rice" in ing_lower and any(raw_kw in ing_lower for raw_kw in ("raw", "uncooked", "dry")):
        raw_rice_candidates = [
            food for food in usda_foods
            if "rice" in food["display_name"].lower()
            and ("uncooked" in food["display_name"].lower() or food.get("is_raw"))
        ]
        if raw_rice_candidates:
            best_raw = max(
                raw_rice_candidates,
                key=lambda food: bigram_similarity(search, normalise(food["display_name"]))
            )
            return dict(best_raw), 0.95, "high", None

    # â”€â”€ Direct FDC ID pin â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if pinned_fdc_id:
        food = usda_foods.get(pinned_fdc_id)
        if food:
            return dict(food), 0.95, "high", None
        if pinned_fdc_id.startswith("B_") and _get_branded():
            branded_food = _get_branded().get(pinned_fdc_id)
            if branded_food:
                return dict(branded_food), 0.95, "high", None

    # â”€â”€ Generic meat â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Short meat names ("beef", "pork", "chicken", "lamb") score poorly via
    # bigram â€” "beef" matches "Beer", "pork" matches "Port", etc.
    # Direct lookup to the generic cooked entry, then MEAT_GENERIC_IDS handles
    # yield factors downstream.
    GENERIC_MEAT_IDS = {
        "beef":    "169484",   # Beef, cooked (composite)
        "pork":    "1_167855", # Pork, cooked
        "chicken": "171477",   # Chicken, broilers, meat and skin, cooked
        "lamb":    "172509",   # Lamb, composite
    }
    GENERIC_MEAT_EXCLUDES = {
        "broth","stock","bouillon","powder","extract","sauce","sausage",
        "bacon","ham","pepperoni","salami","pastrami","jerky","biltong",
        "liver","kidney","heart","tongue","tripe","fat","skin","bone",
        # Specific cuts â€” let these fall through to bigram matching
        "thigh","breast","wing","drumstick","leg","loin","chop","rib",
        "belly","shoulder","neck","shank","fillet","tenderloin","cutlet",
        "brisket","chuck","sirloin","rump","flank","round","spare",
    }
    # Only fire for bare/simple meat references, not specific cuts (those
    # match fine via bigram or MINCE_IDS/MEAT_GENERIC_IDS fallback).
    for generic_meat_kw, fdc_id in GENERIC_MEAT_IDS.items():
        if (generic_meat_kw in ing_lower
                and not any(ex in ing_lower for ex in GENERIC_MEAT_EXCLUDES)
                and not ("ground" in ing_lower or "mince" in ing_lower or "minced" in ing_lower)):
            food = usda_foods.get(fdc_id)
            if food:
                tagged = dict(food)
                # Suppress yield when recipe weight is already post-cook
                if not is_cooked:
                    tagged["_yield_factor"] = MEAT_GENERIC_IDS.get(generic_meat_kw, (None, 1.0))[1] if generic_meat_kw in MEAT_GENERIC_IDS else None
                return tagged, 0.90, "high", None
            break
    # Bird-specific eggs have their own USDA rows, so keep them out of the
    # generic chicken egg fast-path and return the species row directly.
    SPECIES_EGG_IDS = {
        "duck": "172189",
        "goose": "172190",
        "quail": "172191",
        "turkey": "172192",
    }
    if "egg" in ing_lower:
        for species_kw, fdc_id in SPECIES_EGG_IDS.items():
            if species_kw in ing_lower:
                food = usda_foods.get(fdc_id)
                if food:
                    return food, 0.95, "high", None

    # Bigram matching scores too low on "egg" to clear MIN_CONFIDENCE.
    # Direct lookup bypasses matching entirely.
    EGG_EXCLUDES = {"noodle", "pasta", "roll", "mayo", "mayonnaise",
                    "eggplant", "custard", "tofu", "sponge", "waffle", "roe",
                    "yolk", "white", "salted", "duck", "preserved"}
    if "egg" in ing_lower and not any(ex in ing_lower for ex in EGG_EXCLUDES):
        # Check most specific first (yolk) before generic egg
        for kw, fdc_id in [("egg", "171287")]:
            if kw in ing_lower:
                food = usda_foods.get(fdc_id)
                if food:
                    return food, 0.95, "high", None

    # â”€â”€ Tofu â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Mackerel is a very specific whole-food match; avoid letting it drift to
    # branded fish products or generic seafood items.
    MACKEREL_EXCLUDES = {"smoked", "canned", "pate", "spread", "roe", "salad", "dip", "paste"}
    if "mackerel" in ing_lower and not any(ex in ing_lower for ex in MACKEREL_EXCLUDES):
        if "raw" in ing_lower or "uncooked" in ing_lower:
            food = usda_foods.get("175119")
            if food:
                return food, 0.95, "high", None
        else:
            food = usda_foods.get("175120") or usda_foods.get("175119")
            if food:
                return food, 0.95, "high", None

    # Shrimp should resolve to a plain whole-food shrimp entry rather than a
    # branded or processed product, and "whole shrimp" still means 1 piece.
    SHRIMP_EXCLUDES = {"breaded", "fried", "tempura", "canned", "smoked", "dried", "powder", "paste", "sauce", "surimi"}
    if "shrimp" in ing_lower and not any(ex in ing_lower for ex in SHRIMP_EXCLUDES):
        cookedish = any(kw in ing_lower for kw in ("cooked", "boiled", "steamed", "sauteed", "sauted", "grilled", "fried"))
        if unit.lower() in VOLUMETRIC_UNITS:
            shrimp_search = normalise(strip_prep(ingredient))
            shrimp_search = _strip_color_words_if_process(shrimp_search)
            shrimp_query_tokens = normalise(shrimp_search).split()
            shrimp_candidates = [
                f for f in usda_foods
                if "shrimp" in f["display_name"].lower()
            ]
            scored = []
            for food in shrimp_candidates:
                if not _has_compatible_volumetric_serving(food, unit):
                    continue
                score = bigram_similarity(shrimp_search, normalise(food["display_name"]))
                score += _exact_label_bonus(shrimp_search, food["display_name"])
                score += _label_prefix_bonus(shrimp_search, food["display_name"])
                score += _contiguous_phrase_bonus(shrimp_search, food["display_name"])
                score += _front_label_match_bonus(shrimp_search, food["display_name"])
                score -= _single_token_prefix_penalty(shrimp_search, food["display_name"])
                score -= _compound_prefix_penalty(shrimp_search, food["display_name"])
                score -= _prefix_dish_penalty(shrimp_search, food["display_name"])
                if len(shrimp_query_tokens) > 1:
                    score -= _missing_query_token_penalty(shrimp_search, food["display_name"])
                if score >= MIN_CONFIDENCE:
                    scored.append((score, food))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                canned_scored = [item for item in scored if "canned" in item[1]["display_name"].lower()]
                if canned_scored:
                    canned_scored.sort(key=lambda x: x[0], reverse=True)
                    best_score, best_food = canned_scored[0]
                    return best_food, best_score, "low" if best_score < 0.55 else "high", None
                return scored[0][1], scored[0][0], "low" if scored[0][0] < 0.55 else "high", None
        else:
            if cookedish:
                food = usda_foods.get("175180")
                if food:
                    return food, 0.95, "high", None
            food = usda_foods.get("174210") or usda_foods.get("175180")
            if food:
                return food, 0.95, "high", None

    # Pork cutlets are better represented by the USDA pork steak survey row
    # than by generic pork or a chop-family fallback. Tag the cut keyword as
    # "steak" so the portion picker chooses "1 steak, any size".
    if "pork" in ing_lower and "cutlet" in ing_lower:
        food = usda_foods.get("2705873")
        if food:
            tagged = dict(food)
            tagged["_cut_keyword"] = "steak"
            return tagged, 0.95, "high", None

    # Tofu is subtype-sensitive: firm, soft, extra-firm, fried, and regular
    # should not collapse into one generic tofu entry.
    if "tofu" in ing_lower:
        tofu_checks = [
            (("silken",), None),
            (("extra firm", "extra-firm", "super firm", "super-firm"), "174290"),
            (("dried frozen", "dried-frozen", "koyadofu"), "172450"),
            (("fried", "aburaage"), "172451"),
            (("fermented", "fuyu"), "174280"),
            (("soft",), "172449"),
            (("firm", "nigari"), "172475"),
            (("regular",), "172476"),
        ]
        for needles, fdc_id in tofu_checks:
            if any(n in ing_lower for n in needles):
                if fdc_id:
                    food = usda_foods.get(fdc_id)
                    if food:
                        return food, 0.95, "high", None
                break
        # Bare "tofu" defaults to firm tofu, but silken and super-firm are
        # better handled by the branded fallback rules.
        if not any(n in ing_lower for n in ("silken", "super firm", "super-firm")):
            for fdc_id in ("172475", "172448", "172476"):
                food = usda_foods.get(fdc_id)
                if food:
                    return food, 0.95, "high", None

    if "honey" in ing_lower:
        food = usda_foods.get("169640")
        if food:
            return food, 0.95, "high", None

    # â”€â”€ Salmon â€” direct FDC ID lookup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # "salmon" bigram-matches "Almonds" (shared al/lm/mo/on bigrams).
    SALMON_EXCLUDES = {"smoked", "canned", "oil", "sauce", "burger",
                       "cake", "loaf", "cream", "pink", "chum", "sockeye",
                       "chinook", "coho"}
    if "salmon" in ing_lower and not any(ex in ing_lower for ex in SALMON_EXCLUDES):
        food = usda_foods.get("2684441")
        if food:
            return food, 0.95, "high", None

    usda_food, usda_score, usda_alt = None, 0.0, None
    best_any_food, best_any_score, best_any_alt = None, -1.0, None
    usda_food, usda_score, usda_alt = _score_list(search_match, usda_foods, boost_weight, boosted, is_processed, is_cooked, unit)
    if usda_score < threshold and cooked_stripped_source.lower() != search_source.lower():
        cooked_stripped_search = normalise(strip_prep(cooked_stripped_source))
        cooked_stripped_match = _strip_color_words_if_process(
            cooked_stripped_search if unit.lower() in VOLUMETRIC_UNITS else cooked_stripped_search
        )
        cooked_food, cooked_score, cooked_alt = _score_list(
            cooked_stripped_match,
            usda_foods,
            boost_weight,
            boosted,
            is_processed,
            is_cooked,
            unit,
        )
        if cooked_food and cooked_score > usda_score:
            usda_food, usda_score, usda_alt = cooked_food, cooked_score, cooked_alt
    if usda_food and usda_score > best_any_score:
        best_any_food, best_any_score, best_any_alt = usda_food, usda_score, usda_alt

    usda_exact = False
    if usda_food:
        usda_exact = (
            normalise(usda_food["display_name"]) == search_exact
            or normalise(usda_food.get("item_name", "")) == search_exact
            or normalise(usda_alt or "") == search_exact
        )

    branded_food = None
    branded_score = 0.0
    branded_exact = False
    if _get_branded():
        branded_food, branded_score, _ = _score_list(search_match, _get_branded(), boost_weight, boosted, is_cooked=is_cooked, unit=unit)
        if branded_food:
            branded_exact = (
                normalise(branded_food["display_name"]) == search_exact
                or normalise(branded_food["item_name"]) == search_exact
            )

    # A USDA staple whose label contains *every* query token is the
    # canonical choice for a recipe, so prefer it before the branded
    # fallback even when its score sits below MIN_CONFIDENCE. Without this,
    # a plain USDA entry ("Fish, tuna, canned", ~0.57) loses to a
    # keyword-stuffed branded name ("Canned Light Tuna In Sauce", ~1.07).
    # This mirrors the token-cover acceptance rule branded already get
    # (score >= 0.45 with full token coverage), applied to USDA and first.
    usda_token_cover = False  # systemic staple-preference rule
    if usda_food and len(query_tokens) > 1:
        usda_label_tokens = (
            set(normalise(usda_food["display_name"]).split())
            | set(normalise(usda_food.get("item_name", "")).split())
            | set(normalise(usda_alt or "").split())
        )
        usda_token_cover = all(
            _token_in_label(tok, usda_label_tokens) for tok in query_tokens)

    if usda_food and (usda_score >= MIN_CONFIDENCE
                      or (usda_token_cover and usda_score >= 0.45)):
        # Tag cooked meat matches with yield factor before returning,
        # so build_output_rows can apply rawâ†’cooked shrinkage.
        if meat_kw and not usda_food.get("is_raw", False):
            _, yield_factor = MEAT_GENERIC_IDS.get(meat_kw, (None, 1.0))
            tagged = dict(usda_food)
            # Suppress yield when recipe weight is already post-cook
            tagged["_yield_factor"] = None if is_cooked else yield_factor
            tagged["_meat_keyword"] = meat_kw
            return tagged, usda_score, ("high" if usda_score >= 0.55 else "low"), usda_alt
        return usda_food, usda_score, ("high" if usda_score >= 0.55 else "low"), usda_alt

    # —— USDA Branded pass ——————————————————————————————————
    if _get_branded() and not meat_kw:
        if branded_food is None:
            branded_food, branded_score, _ = _score_list(
                search_match, _get_branded(), boost_weight, boosted,
                is_cooked=is_cooked, unit=unit)
        if branded_food and branded_score > best_any_score:
            best_any_food, best_any_score, best_any_alt = branded_food, branded_score, None
        branded_token_cover = False
        if branded_food:
            branded_tokens = set(normalise(branded_food["display_name"]).split()) | set(normalise(branded_food["item_name"]).split())
            branded_token_cover = len(query_tokens) > 1 and all(_token_in_label(tok, branded_tokens) for tok in query_tokens)
            if branded_token_cover and branded_score < 0.45:
                branded_food = None
                branded_score = 0.0
        if branded_food and (branded_score >= MIN_CONFIDENCE or (branded_token_cover and branded_score >= 0.45)):
            return branded_food, branded_score, ("high" if branded_score >= 0.55 else "low"), None


    if meat_kw:
        usda_is_weak = not usda_food or usda_score < MEAT_FALLBACK_THRESHOLD
        if usda_is_weak:
            # Meat cuts should use generic USDA entry â€” a generic USDA entry is always
            # more appropriate than a branded product.
            generics = _get_meat_generics(usda_foods)
            if meat_kw in generics:
                generic_food, yield_factor = generics[meat_kw]
                tagged = dict(generic_food)
                tagged["_meat_generic"] = True
                # Suppress yield when recipe weight is already post-cook
                tagged["_yield_factor"] = None if is_cooked else yield_factor
                tagged["_meat_keyword"] = meat_kw
                return tagged, MEAT_FALLBACK_THRESHOLD, "low", None
        else:
            # USDA found a specific cut â€” tag it with yield factor if cooked
            # so build_output_rows can apply shrinkage to the raw gram target.
            if usda_food and not usda_food.get("is_raw", False):
                _, yield_factor = MEAT_GENERIC_IDS.get(meat_kw, (None, 1.0))
                tagged = dict(usda_food)
                # Suppress yield when recipe weight is already post-cook
                tagged["_yield_factor"] = None if is_cooked else yield_factor
                tagged["_meat_keyword"] = meat_kw
                return tagged, usda_score, ("high" if usda_score >= 0.55 else "low"), usda_alt

    # â”€â”€ Location-prefix fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Check BEFORE the MIN_CONFIDENCE early exit so "Thai basil leaves" can
    # retry as "basil" rather than returning None from a weak rhubarb match.
    LOCATION_PREFIXES = {
        "thai", "chinese", "japanese", "korean", "vietnamese", "filipino",
        "italian", "french", "greek", "mexican", "indian", "spanish",
        "middle eastern", "persian", "turkish", "lebanese", "moroccan",
        "indonesian", "malaysian", "taiwanese", "cantonese", "szechuan",
        "sichuan", "cambodian", "burmese", "dutch", "german", "portuguese",
        "american", "british", "australian", "african", "caribbean",
    }
    first_word = ingredient.lower().split()[0] if ingredient.split() else ""
    if first_word in LOCATION_PREFIXES and (not usda_food or usda_score < MIN_CONFIDENCE):
        stripped_ing = " ".join(ingredient.split()[1:])
        if stripped_ing:
            _NOISE = r"\b(leaves|leaf|flakes|powder|paste|sauce|oil|seeds|"
            _NOISE += r"flower|flowers|florets|stalks|stems|shoots|cloves)\b"
            stripped_clean = re.sub(_NOISE, "", stripped_ing, flags=re.I).strip()
            stripped_search = normalise(strip_prep(stripped_clean or stripped_ing))
            s_food, s_score, s_alt = _score_list(_strip_color_words_if_process(stripped_search), usda_foods,
                                                  boost_weight, boosted, is_cooked=is_cooked, unit=unit)
            if s_food and s_score >= 0.45:
                return s_food, s_score, ("high" if s_score >= 0.55 else "low"), s_alt

    if best_any_food is not None and best_any_score >= threshold:
        best_any_score = max(best_any_score, 0.0)
        return best_any_food, best_any_score, ("high" if best_any_score >= 0.55 else "low"), best_any_alt

    return None, max(usda_score, 0.0), "none", None
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
        elif "to taste" in notes:
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

    # Recompute sub-template reference rows whose referenced template was updated.
    for r in merged:
        if (r.get("_type") == "data"
                and r.get("_source") == "sub_template"
                and r.get("sub_template_id","")):
            ref_tid = r["sub_template_id"]
            if ref_tid in new_tids:  # referenced template was just updated
                multiplier = float(r.get("portion_amt") or 1.0)
                ref_cal = _sub_template_calories(ref_tid, merged)
                if ref_cal is not None:
                    r["calories_kcal"] = ref_cal
                    r["cal_tot"]       = round(ref_cal * multiplier, 1)
                    r["notes"]         = f"sub-template Ã—{multiplier} [recomputed]"

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
    if "fl oz" in low or "fluid ounce" in low:
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
    m = re.match(r"^([\d.]+)\s+([\d.]+)\s+\S", label.strip())
    if m:
        first, second = float(m.group(1)), float(m.group(2))
        # Leading 1 or 1.0 followed by another number â†’ serving count pattern
        if abs(first - 1.0) < 1e-9:
            return second
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
        if abs(p.get("gram_weight", 100.0) - 100.0) <= 1.0:
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


def pick_best_portion(food, unit, gram_target, qty=1.0, ingredient="", 
                      boost_rules=None):
    portions = food.get("portions", [])
    if not portions:
        return None
    if food.get("source") == "off":
        serving = next(
            (p for p in portions
             if p.get("portion_idx", 0) == 1 and abs(p["gram_weight"] - 100.0) > 1.0),
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
             if p.get("portion_idx", 0) == 1 and abs(p["gram_weight"] - 100.0) > 1.0),
            None,
        )
        if real_serving:
            # Branded foods often have both a 100g basis and a package serving.
            # Prefer the actual serving so the output uses the package label
            # instead of collapsing back to an artificial 100g portion.
            return real_serving
    if boost_rules and ingredient:
        override = get_portion_override(ingredient, boost_rules, unit)
        if override:
            return override
    keywords = PORTION_UNIT_KEYWORDS.get(unit.lower(), [])
    # If food was matched via CHICKEN_CUT_IDS, use the cut keyword to find
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
    is_piece = is_unitless or unit.lower() in ("piece", "pieces")
    is_slice = unit.lower() in ("slice", "slices")
    if is_unitless:
        keywords = PORTION_UNIT_KEYWORDS.get("piece", [])
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
            # Fall through to general keyword scan if no size match
        # For unitless/piece ingredients, apply size preference logic:
        # - If the ingredient names a size (large/small/medium), try to match it first.
        # - Otherwise default to medium if available.
        # Either way fall through to the general keyword scan if nothing matched.
        if is_piece and not food.get("_cut_keyword"):
            ing_lower = ingredient.lower()
            specified_size = next((sz for sz in ("large", "small", "medium") if sz in ing_lower), None)
            preferred = specified_size or "medium"
            for p in portions:
                # Strip parenthetical content before checking â€” prevents "1.0 cup
                # (4.86 large eggs)" from matching a search for "large".
                # Use word-boundary match so "large" doesn't match "extra large".
                label_no_parens = re.sub(r"\([^)]*\)", "", p["label"]).lower().strip()
                if re.search(r"(?<!\w)" + re.escape(preferred) + r"(?!\w)", label_no_parens):
                    # Exclude labels where the preferred size is preceded by a modifier
                    # like "extra" â€” only accept bare size labels e.g. "1.0 large".
                    if not re.search(r"\b(?:extra|very|super)\s+" + re.escape(preferred), label_no_parens):
                        return p
        # For cup quantities < 0.25, prefer tbsp/tsp portions when a sane
        # portion_amt results. Bootstrap recipe_grams from the cup portion's
        # gram_weight so this works even when gram_target is None (vol solids).
        if unit.lower() in ("cup", "cups") and qty < 0.25:
            cup_p = next((p for p in portions if "cup" in p["label"].lower()), None)
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
        for p in portions:
            if any(kw in p["label"].lower() for kw in keywords):
                return p
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
        # If the food has a genuine serving size but no volumetric serving,
        # prefer the real serving over collapsing to the 100g basis. This is
        # especially useful for packaged foods that expose servings as PACK,
        # BOX, BAR, etc. and would otherwise lose their actual portion label.
        real_serving = next(
            (p for p in portions
             if p.get("portion_idx", 0) == 1 and abs(p["gram_weight"] - 100.0) > 1.0),
            None,
        )
        if real_serving:
            return real_serving
        return None
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


def _sub_template_calories(ref_tid: str, rows: list) -> float | None:
    """
    Sum cal_tot for all data rows belonging to ref_tid.
    Returns None if the template isn't found.
    """
    total = 0.0
    found = False
    for r in rows:
        if r.get("template_id","") == ref_tid and r.get("_type") == "data":
            found = True
            try:
                cal = float(r.get("cal_tot") or r.get("calories_kcal") or 0)
                total += cal
            except (ValueError, TypeError):
                pass
    return round(total, 1) if found else None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Core pipeline
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def build_output_rows(recipes_path, boost_rules=None, threshold=0.45,
                      existing_rows=None):
    if existing_rows is None:
        existing_rows = []
    output_rows=[]
    rows_by_template=defaultdict(list)
    match_cache: dict[tuple, tuple] = {}
    with open(recipes_path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows_by_template[row.get("template_id","").strip()].append(row)

    # ── Pre-fetch USDA indexes in parallel ──────────────────────────────────
    # Collect all unique search queries across all ingredients, then fire
    # them concurrently so the network round-trips overlap.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_search_queries: set[str] = set()
    for tid, ing_rows in rows_by_template.items():
        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient", "").strip()
            unit = ing_row.get("unit", "").strip()
            if "to taste" in unit.lower() or unit.lower() == "sub_template":
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

        for ing_row in ing_rows:
            ingredient=ing_row.get("ingredient","").strip()
            qty_raw=ing_row.get("qty","").strip()
            unit=ing_row.get("unit","").strip()
            section=ing_row.get("section","").strip() or "Main"
            size_hint=ing_row.get("size_hint","").strip()
            is_cooked = ing_row.get("is_cooked","").strip().lower() in ("true","1","yes")
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

            # Sub-template reference â€” look up aggregated calories from existing output.
            if unit.lower() == "sub_template":
                try: multiplier = float(qty_raw) if qty_raw else 1.0
                except ValueError: multiplier = 1.0
                ref_tid = ingredient.strip()
                # Find total calories for one serving of the referenced template
                ref_cal = _sub_template_calories(ref_tid, existing_rows + output_rows)
                if ref_cal is None:
                    output_rows.append({
                        "_type":"data","_confidence":"none","_source":"none",
                        "template_id":tid,"template_name":template_name,
                        "other_names":other_names,
                        "category":category,"component_label":ref_tid,
                        "sub_template_id":ref_tid,
                        "portion_amt":multiplier,
                        "notes":f"UNRESOLVED SUB-TEMPLATE '{ref_tid}'",
                        "section":section,
                    })
                else:
                    agg_cal   = round(ref_cal * multiplier, 1)
                    output_rows.append({
                        "_type":        "data",
                        "_confidence":  "high",
                        "_source":      "sub_template",
                        "template_id":  tid,
                        "template_name":template_name,
                        "other_names":  other_names,
                        "category":     category,
                        "component_label": ref_tid,
                        "matched_food_name": "",
                        "food_id":      "",
                        "portion_id":   "",
                        "portion_amt":  multiplier,
                        "portion_description": f"Ã—{multiplier} of {ref_tid}",
                        "calories_kcal": ref_cal,
                        "cal_tot":       agg_cal,
                        "sub_template_id": ref_tid,
                        "notes":        f"sub-template Ã—{multiplier}",
                        "section":      section,
                    })
                data_row_indices.append(len(output_rows) + 1)
                continue

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
            if match_key in match_cache:
                food, score, confidence, matched_alt = match_cache[match_key]
            else:
                food, score, confidence, matched_alt = match_ingredient(
                    ingredient, boost_rules, threshold, category, unit,
                    is_cooked=is_cooked)
                match_cache[match_key] = (food, score, confidence, matched_alt)

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
            # Apply a 2Ã— yield factor to convert raw â†’ cooked gram weight.
            if (yield_factor is None
                    and gram_target is not None
                    and _pasta_keyword(ingredient)):
                yield_factor = PASTA_YIELD_FACTOR

            effective_gram_target=gram_target
            if yield_factor and gram_target is not None:
                effective_gram_target=gram_target*yield_factor

            portion=pick_best_portion(food,unit,effective_gram_target,qty,ingredient_for_portion,boost_rules)
            if portion is None and unit.lower() not in VOLUMETRIC_UNITS:
                portion=food["portions"][0] if food["portions"] else None

            u_low=unit.lower()
            is_countable=u_low in ("piece","pieces","clove","cloves","unit","units","item","serving","servings","sheet","sheets","leaf","leaves","stalk","stalks","slice","slices","strip","strips","spear","spears","head","heads","ear","ears","fillet","fillets","steak","steaks","patty","patties","chop","chops","drumstick","drumsticks","knob","knobs","cube","cubes","block","blocks","stick","sticks","wrapper","wrappers","whole")
            display_label=matched_alt if matched_alt else ingredient
            vol_mismatch=False

            if portion is None:
                portion_id=f"{food['fdc_id']}-0"
                portion_desc="100g"
                # cal_formula is per-100g; portion_amt must be in 100g units.
                portion_amt=effective_gram_target / 100 if effective_gram_target is not None else qty
                if source == "branded":
                    serving_portion = next(
                        (p for p in food.get("portions", [])
                         if p.get("portion_idx", 0) == 1 and p.get("gram_weight")),
                        None,
                    )
                    if serving_portion:
                        cal_formula = round(
                            food.get("energy_kcal", 0.0) * 100 / serving_portion["gram_weight"],
                            1,
                        )
                    else:
                        cal_formula = round(food.get("energy_kcal", 0.0), 1)
                else:
                    cal_formula=round(food.get("energy_kcal", 0.0), 1)
            else:
                portion_id=portion["portion_id"]
                portion_desc=f"{portion['label']} ({portion['gram_weight']:.0f} g)"

                if source=="usda":
                    gcol=portion["gram_col"]
                    food_row=food["row"]
                    cal_formula=round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                elif source == "branded":
                    food_row=food["row"]
                    if portion.get("portion_idx", 0) == 0:
                        serving_portion = next(
                            (p for p in food.get("portions", [])
                             if p.get("portion_idx", 0) == 1 and p.get("gram_weight")),
                            None,
                        )
                        if serving_portion:
                            cal_formula = round(
                                food.get("energy_kcal", 0.0) * 100 / serving_portion["gram_weight"],
                                1,
                            )
                        else:
                            cal_formula = round(food.get("energy_kcal", 0.0), 1)
                    else:
                        cal_formula=round(food.get("energy_kcal", 0.0), 1)
                else:
                    sheet="foods"
                    food_row=food["row"]
                    if portion.get("portion_idx",0)==0:
                        cal_formula=round(food.get("energy_kcal", 0.0), 1)
                    else:
                        cal_formula=round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

                label_unit = _portion_label_unit(portion["label"])
                if is_countable or not unit or portion.get("_cube_match"):
                    if portion.get("_cube_match") or u_low in ("serving", "servings"):
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
                            portion_amt = qty
                            vol_mismatch = True
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
                            portion_amt = qty
                            vol_mismatch = True

            # â”€â”€ Portion sanity check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # If portion_amt is suspiciously small (<0.1) or large (>10),
            # compute recipe_grams and find the portion whose gram_weight is
            # closest â€” that's a better fit than the original selection.
            # Skip for countable items and the 100g-basis path (portion is None).
            if (portion is not None and not is_countable
                    and not vol_mismatch
                    and (portion_amt < 0.1 or portion_amt > 10)):
                recipe_grams = portion_amt * portion["gram_weight"]
                all_portions = food.get("portions", [])
                if len(all_portions) > 1:
                    better = min(all_portions,
                                 key=lambda p: abs(p["gram_weight"] - recipe_grams))
                    if better["portion_id"] != portion["portion_id"]:
                        portion = better
                        portion_id   = portion["portion_id"]
                        portion_desc = f"{portion['label']} ({portion['gram_weight']:.0f} g)"
                        portion_amt  = recipe_grams / portion["gram_weight"]
                        if source == "usda":
                            cal_formula = round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)
                        elif source == "branded":
                            if portion.get("portion_idx", 0) == 0:
                                serving_portion = next(
                                    (p for p in food.get("portions", [])
                                     if p.get("portion_idx", 0) == 1 and p.get("gram_weight")),
                                    None,
                                )
                                if serving_portion:
                                    cal_formula = round(
                                        food.get("energy_kcal", 0.0) * 100 / serving_portion["gram_weight"],
                                        1,
                                    )
                                else:
                                    cal_formula = round(food.get("energy_kcal", 0.0), 1)
                            else:
                                cal_formula = round(food.get("energy_kcal", 0.0), 1)
                        else:
                            if portion.get("portion_idx", 0) == 0:
                                cal_formula = round(food.get("energy_kcal", 0.0), 1)
                            else:
                                cal_formula = round((portion["gram_weight"] / 100) * food.get("energy_kcal", 0.0), 1)

            cal_tot_formula=round(cal_formula * portion_amt, 1) if isinstance(cal_formula, float) else ""
            source_tag=" [BRANDED]" if source=="branded" else ""
            yield_tag=f" [yield {yield_factor}]" if yield_factor else ""
            vol_note = "VOL UNIT MISMATCH (3 tsp=1 tbsp, 16 tbsp=1 cup) " if vol_mismatch else ""
            note_text=f"{vol_note}{'LOW CONF ' if confidence=='low' else ''}score {score:.2f}{source_tag}{yield_tag}"

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
            })
            data_row_indices.append(current_excel_row)

        if data_row_indices:
            output_rows.append({
                "_type":"subtotal","template_id":tid,
                "start_row":data_row_indices[0],"end_row":data_row_indices[-1],
            })

    sys.stderr.write("\r" + " " * 80 + "\r")  # clear progress bar
    sys.stderr.flush()
    return output_rows


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
    new_rows=build_output_rows(args.recipes, boost_rules, args.threshold,
                               existing_rows=existing_rows)

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
    print(f"    This run: {len(new_data)} ingredients  |  "
          f"USDA: {len(usda_hi)} high / {len(usda_lo)} low  |  "
          f"Branded: {len(brd_hi)} high / {len(brd_lo)} low  |  "
          f"unmatched: {len(unmatched)}")
    print(f"    Total in output: {len(data_rows)} ingredients across all templates.")

    print(f"[→] Writing output: {xlsx_path}")
    if HAS_OPENPYXL:
        write_xlsx(output_rows, xlsx_path)
    else:
        print(f"[!] openpyxl unavailable — skipping xlsx.")
    write_csv(output_rows, csv_path)

if __name__=="__main__":
    main()
