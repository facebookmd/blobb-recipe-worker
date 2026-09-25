#!/usr/bin/env python3
from __future__ import annotations
"""
parse_recipe.py
---------------
Parse one or more freeform recipe ingredient lists into recipes.csv,
preview each one interactively, then run recipe_matcher.py.

INPUT MODES
  Multiple files:
    python parse_recipe.py adobo.txt sinigang.txt caesar.txt

  Single file with multiple recipes (separated by ---, ===, or 3+ blank lines):
    python parse_recipe.py all_recipes.txt

  Both at once:
    python parse_recipe.py batch.txt extra.txt

OUTPUT
  All recipes are collected into one recipes.csv, then the matcher runs once.
  Use --append to add to an existing templates_output.xlsx instead of overwriting.

RECIPE METADATA
  Priority: detected title line in file  >  filename stem
  Use --category to tag all recipes in a run with the same category.

FORMAT SUPPORT
  ▢ / - [ ] / * [ ]   Markdown checkboxes
  * / - / • / numbers  Bullets and numbered lists
  __bold__ / **bold**  Copy-paste bold markers (inner text kept)
  (note 1) etc.        Stripped
  ½ ¼ ¾ ⅓ ⅔ ⅛        Unicode fractions
  1/2  1 1/2  3-4      ASCII fractions, mixed numbers, ranges
  150g  2tbsp           Number glued to unit
  to taste / as needed  Flagged as note rows (no calories)
"""

import argparse
import csv
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# ── Unit vocabulary ───────────────────────────────────────────────────────────
UNIT_MAP = {
    "kg":"kg","kilo":"kg","kilos":"kg","kilogram":"kg","kilograms":"kg",
    "g":"g","gram":"g","grams":"g",
    "lb":"lb","lbs":"lb","pound":"lb","pounds":"lb",
    "oz":"oz","ounce":"oz","ounces":"oz",
    "ml":"ml","mL":"ml","milliliter":"ml","millilitre":"ml",
    "milliliters":"ml","millilitres":"ml",
    "l":"l","liter":"l","litre":"l","liters":"l","litres":"l",
    "tsp":"tsp","teaspoon":"tsp","teaspoons":"tsp",
    "tbsp":"tbsp","tablespoon":"tbsp","tablespoons":"tbsp",
    "T":"tbsp","t":"tsp",
    "c":"cup","cup":"cup","cups":"cup",
    "fl oz":"fl oz","fluid ounce":"fl oz","fluid ounces":"fl oz",
    "pint":"pint","pints":"pint","pt":"pint",
    "quart":"quart","quarts":"quart","qt":"quart",
    "gallon":"gallon","gallons":"gallon","gal":"gallon",
    "piece":"piece","pieces":"piece","pc":"piece","pcs":"piece",
    "cube":"piece","cubes":"piece",
    "wrapper":"piece","wrappers":"piece",
    "serving":"serving","servings":"serving",
    "clove":"clove","cloves":"clove",
    "slice":"slice","slices":"slice",
    "stalk":"stalk","stalks":"stalk",
    "bunch":"bunch","bunches":"bunch",
    "head":"head","heads":"head",
    "whole":"whole",
    "can":"can","cans":"can",
    "sachet":"sachet","sachets":"sachet",
    "pack":"pack","packs":"pack","packet":"pack","packets":"pack",
    "block":"block","blocks":"block",
    "knob":"knob","thumb":"thumb",
    "stick":"stick","sticks":"stick",
    "drop":"drop","drops":"drop",
    "dash":"dash","dashes":"dash",
    "pinch":"pinch","pinches":"pinch",
    "handful":"handful","handfuls":"handful",
    "sheet":"sheet","sheets":"sheet",
}

_UNIT_PATTERN = "|".join(re.escape(k) for k in sorted(UNIT_MAP, key=len, reverse=True))

TO_TASTE_RE = re.compile(
    r"\b(to taste|to\s*taste|as needed|as required|for garnish|for serving|"
    r"optional|a pinch|a dash|season(?:ing)? to taste)\b", re.I)

UNICODE_FRACS = {
    "½":"1/2","¼":"1/4","¾":"3/4","⅓":"1/3","⅔":"2/3",
    "⅛":"1/8","⅜":"3/8","⅝":"5/8","⅞":"7/8",
    "⅙":"1/6","⅚":"5/6","⅕":"1/5","⅖":"2/5","⅗":"3/5","⅘":"4/5",
}

STRIP_PATTERNS = [
    re.compile(r"\(note\s*\d*[:\)]?[^)]*\)", re.I),
    # "*see note*", "*see notes above*", "**see notes", ", see note 2" —
    # annotation markers, strip entirely. Must run BEFORE the bare `note \d+`
    # stripper (which would consume "note 2" and leave a dangling ", see") and
    # BEFORE the general *...* pattern (which would preserve the inner text).
    re.compile(r"\*+\s*see\s+notes?\b[^*]*\**", re.I),
    re.compile(r",\s*see\s+notes?\b[^,]*$", re.I),
    re.compile(r"\bnote\s*\d+\b", re.I),
    re.compile(r"__([^_]+)__"),
    re.compile(r"\*\*([^*]+)\*\*"),
    re.compile(r"\*([^*]+)\*"),
    re.compile(r"`([^`]+)`"),
]

DROP_PARENS_RE = re.compile(r"\([^)]*\)", re.I)

PREFIX_RE    = re.compile(r"^[\s▢•\-\*\u2610\u2611\u2612]+")
CHECKBOX_RE  = re.compile(r"^[-*]\s*\[[ xX]\]\s*")
NUMBERED_RE  = re.compile(r"^\d+[.)]\s+")
INLINE_ANNOTATION_RE = re.compile(r",\s*(divided|plus more|to serve|for [a-z ]+).*$", re.I)

# Recipe divider: ---, ===, ***, or a line that is ONLY those chars (3+)
DIVIDER_RE = re.compile(r"^[-=*_]{3,}\s*$")

# Sub-section header within a recipe: "--Salad", "-- Sauce", "--Dressing"
# Two leading dashes, optional space, then the section name.
# Distinct from DIVIDER_RE (3+ dashes alone) and from prep-note dashes
# (which require a leading word and are mid/end of line).
SECTION_HEADER_RE = re.compile(r"^--\s*(\S.*?)\s*$")

DEFAULT_SECTION = "Main"


# ═══════════════════════════════════════════════════════════════════════════════
# Text utilities
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_fractions(text: str) -> str:
    for uc, asc in UNICODE_FRACS.items():
        text = text.replace(uc, f" {asc} ")
    text = text.replace("\u2044", "/").replace("\u2215", "/")
    return text


def parse_number(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", token)
    if m:
        n, d = int(m.group(1)), int(m.group(2))
        return n / d if d else None
    try:
        return float(token)
    except ValueError:
        return None


def extract_quantity(text: str) -> tuple[float | None, str]:
    text = normalise_fractions(text).strip()

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s+", text)
    if m:
        return float(m.group(1)), text[m.end():]

    m = re.match(r"^(\d+)\s+(\d+\s*/\s*\d+)\s+", text)
    if m:
        frac = parse_number(m.group(2))
        if frac is not None:
            return float(m.group(1)) + frac, text[m.end():]

    m = re.match(r"^(\d+\s*/\s*\d+)\s+", text)
    if m:
        frac = parse_number(m.group(1))
        if frac is not None:
            return frac, text[m.end():]

    m = re.match(r"^(\d+(?:\.\d+)?)\s+", text)
    if m:
        return float(m.group(1)), text[m.end():]

    # Number glued to unit ("150g", "2tbsp") — use lookahead, leave unit for extract_unit
    m = re.match(r"^(\d+(?:\.\d+)?)(?=" + _UNIT_PATTERN + r"\b)", text)
    if m:
        return float(m.group(1)), text[m.end():]

    return None, text


def extract_unit(text: str) -> tuple[str | None, str]:
    text = text.strip()
    m = re.match(r"^(" + _UNIT_PATTERN + r")\b[\s.,]*", text, re.I)
    if m:
        raw = m.group(1).strip(".")
        canonical = UNIT_MAP.get(raw) or UNIT_MAP.get(raw.lower())
        return canonical, text[m.end():]
    return None, text


# ═══════════════════════════════════════════════════════════════════════════════
# Line cleaning
# ═══════════════════════════════════════════════════════════════════════════════

def clean_line(raw: str) -> str:
    # Normalise unicode fractions BEFORE NFKC — NFKC turns "½" into "1⁄2"
    # which then concatenates with a leading digit: "1½" → "11⁄2" → 5.5 (wrong).
    line = normalise_fractions(raw.strip())
    line = unicodedata.normalize("NFKC", line)
    line = re.sub(r"^#+\s*", "", line)       # markdown headings
    line = CHECKBOX_RE.sub("", line)
    line = NUMBERED_RE.sub("", line)
    line = PREFIX_RE.sub("", line)
    for pat in STRIP_PATTERNS:
        line = pat.sub(lambda m: m.group(1) if m.lastindex else "", line)
    line = INLINE_ANNOTATION_RE.sub("", line)
    line = DROP_PARENS_RE.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Title detection
# ═══════════════════════════════════════════════════════════════════════════════

_UNIT_FIRST_RE = re.compile(r"^(\d|" + _UNIT_PATTERN + r")\b", re.I)

def looks_like_title(line: str) -> bool:
    s = re.sub(r"^#+\s*", "", line).strip()
    if not s or len(s) > 80:
        return False
    if _UNIT_FIRST_RE.match(s):
        return False
    words = s.split()
    # Allow single-word titles (e.g. "Coleslaw", "Adobo") as long as the word
    # doesn't start with a digit and isn't a known unit keyword.
    return len(words) >= 1 and not re.search(r"\d", words[0])


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower().strip()).strip("_")
    if s and "_" not in s:
        s = s + "_"
    return s or "recipe"


# ═══════════════════════════════════════════════════════════════════════════════
# Single-line ingredient parser
# ═══════════════════════════════════════════════════════════════════════════════
def parse_ingredient_line(raw: str) -> dict | None:
    line = clean_line(raw)
    if not line:
        return None

    # Skip metadata lines (e.g. "SOURCE: https://...")
    if re.match(r"^source\s*:", line, re.I):
        return None

    if re.match(
        r"^(ingredients?|instructions?|directions?|method|steps?|for the\s+\w+|"
        r"sauce|marinade|garnish|equipment|notes?|tips?|prep|cook|total)\s*:?$",
        line, re.I
    ):
        return None

    # Sub-template reference: "<qty> <template_id>" where template_id contains
    # an underscore or matches a known slug pattern (no spaces, no units).
    # e.g. "0.5 banh_mi_template" or "1 gyoza_filling"
    SUB_TEMPLATE_RE = re.compile(
        r"^([\d./]+)\s+([a-z][a-z0-9_-]{2,})$", re.I
    )
    m = SUB_TEMPLATE_RE.match(line.strip())
    if m:
        qty_str = normalise_fractions(m.group(1))
        qty_val = parse_number(qty_str.strip())
        ref_id  = m.group(2).strip()
        # Only treat as sub-template if it looks like a slug (has _ or -)
        # and isn't a unit keyword
        if ("_" in ref_id or "-" in ref_id) and ref_id not in UNIT_MAP:
            return {
                "qty":        str(round(qty_val, 6)) if qty_val else "1",
                "unit":       "sub_template",
                "ingredient": ref_id,
                "size_hint":  "",
                "is_cooked":  False,
                "to_taste":   False,
                "raw":        raw.strip(),
            }

    if TO_TASTE_RE.search(line):
        ing = TO_TASTE_RE.sub("", line).strip(" ,;:")
        _, rest = extract_quantity(ing)
        _, rest = extract_unit(rest)
        ing_name = re.sub(r"\([^)]*\)", "", rest).strip(" ,;") or ing.strip(" ,;")
        # Strip trailing prep notes and dashes (same as normal path)
        ing_name = re.sub(r"\s+or\s+\S.*$", "", ing_name, flags=re.I)
        ing_name = re.sub(r"\s*[–—-]+.*$", "", ing_name)
        ing_name = re.sub(r"\s*,\s*(?:finely|thinly|roughly|coarsely|freshly|lightly|"
                          r"chopped|sliced|diced|minced|grated|shredded|peeled|trimmed).*$",
                          "", ing_name, flags=re.I)
        ing_name = ing_name.strip(" ,;:")

        # Salt "to taste" gets a default pinch (1/16 tsp ≈ 0.3g, ~116mg sodium)
        # so sodium tracking has something to work with.
        # "Cooking salt" (used to season water/liquid, not directly consumed)
        # gets a smaller trace amount (0.01 tsp).
        # Other "to taste" ingredients stay as blank note rows.
        SALT_KEYWORDS = {"salt", "asin", "sea salt", "rock salt", "kosher salt",
                         "iodized salt", "table salt"}
        is_salt = any(kw in ing_name.lower() for kw in SALT_KEYWORDS)
        is_cooking_salt = is_salt and ing_name.lower().startswith("cooking")
        if is_salt:
            qty_tsp = 0.01 if is_cooking_salt else round(1/16, 4)
            clean_name = re.sub(r"^cooking\s+", "", ing_name, flags=re.I).strip() if is_cooking_salt else ing_name
            return {"qty": str(qty_tsp), "unit": "tsp",
                    "ingredient": clean_name, "size_hint": "",
                    "is_cooked": False, "to_taste": False, "raw": raw.strip()}

        return {"qty":"","unit":"to taste","ingredient":ing_name,
                "size_hint":"","is_cooked": False,"to_taste":True,"raw":raw.strip()}

    qty_val, rest = extract_quantity(line)
    # Capture decimal-inch size annotation (e.g. 1.5") before stripping,
    # so it can be appended to the ingredient name for portion label matching.
    _inch_m = re.match(r'^(\d+(?:\.\d+)?)"?\s*', rest)
    _inch_size = None
    if _inch_m and '"' in rest[len(_inch_m.group(1)):len(_inch_m.group(1))+2]:
        _inch_size = _inch_m.group(1)
        rest = re.sub(r'^\d+(?:\.\d+)?"\s*', "", rest)
    unit_val, rest = extract_unit(rest)

    # Strip alternative unit measurement: " / 3 oz" or " / 1 lb" etc.
    # Recipe sites often show metric/imperial pairs: "87.5g / 3 oz chicken"
    # Keep the first measurement (already captured), drop the alternative.
    rest = re.sub(r"^\s*/\s*\d+(?:\.\d+)?\s*(?:" + _UNIT_PATTERN + r")\b\s*", "", rest, flags=re.I)

    # Truncate at sentence-style buying/prep notes that follow the ingredient name.
    rest = re.sub(r",\s*(?:NOT |Look |Preferably |Note |See |ideally |preferably |about |approx |if possible )[^.]*\.?[^,]*", "", rest, flags=re.I)
    rest = re.sub(r"\.\s+[A-Z].*$", "", rest)   # truncate at ". Sentence..."

    # Strip " or [alternative]" and " and [form/descriptor]" clauses.
    # Keep the first option only.
    # e.g. "mayonnaise or Kewpie" → "mayonnaise"
    #      "cilantro leaves and small sprigs" → "cilantro leaves"
    rest = re.sub(r"\s+or\s+\S.*$", "", rest, flags=re.I)
    # Strip " and [size/form descriptor]" — but only trailing ones
    rest = re.sub(r"\s+and\s+(?:small|large|fresh|dry|whole|torn|extra|young|baby|mini)\s+\S+.*$", "", rest, flags=re.I)
    # Strip trailing noise words: leaves, sprigs, florets, stalks, etc.
    rest = re.sub(r"\s*,?\s*\b(?:leaves|leaf|sprigs|sprig|florets|floret|stalks|stalk|stems|stem|shoots|fronds)\b.*$", "", rest, flags=re.I)

    # Strip em-dash or spaced-dash purpose notes: "– for cooking", "- for boiling water"
    rest = re.sub(r"\s*[–—-]+\s*(for |to |used |mainly |just ).*$", "", rest, flags=re.I)
    # Also strip bare trailing dash with nothing useful after it
    rest = re.sub(r"\s*[–—-]+\s*$", "", rest)


    rest = re.sub(r"\d+(?:[–-]\d+(?:\.\d+)?)?\s*(?:mm|cm|inch(?:es)?)\b", "", rest, flags=re.I)
    rest = re.sub(r'\d+(?:[./]\d+)?"', "", rest)
    # Clean up orphaned slashes left by size stripping
    rest = re.sub(r"\s*/\s*(?=[a-zA-Z])", " ", rest)
    rest = re.sub(r"\s*/\s*$", "", rest)

    # Strip trailing physical description fragments left after size stripping
    # e.g. ", even thickness with flat, unwrinkled skin"
    rest = re.sub(r",\s*(?:even|flat|equal|uniform|smooth|unwrinkled)[^,;.]*", "", rest, flags=re.I)

    # Truncate at comma followed by a prep/cut/state word — anywhere downstream.
    # Uses non-greedy `[^.;]*?` between the comma and the prep word so chained
    # commas like "banana prawns, head, shells and guts removed" all collapse
    # to "banana prawns" (matches at the first comma, eats through to "removed").
    # e.g. "carrots , peeled cut into batons" → "carrots"
    #      "chicken , skin removed"           → "chicken"
    #      "cucumber, seeds removed"          → "cucumber"
    _PREP_COMMA_PAT = (
        r"peeled|peel|cut |sliced|slice|chopped|chop|diced|dice|minced|mince|"
        r"trimmed|trim|halved|quartered|crushed|grated|shredded|torn|"
        r"julienned|julienne|cleaned|cored|pitted|seeded|hulled|stemmed|"
        r"skinned|gutted|shelled|"
        r"deveined|deboned|skin removed|skin on|bones removed|"
        r"\w+\s+removed|removed|"
        r"finely|thinly|roughly|coarsely|freshly|lightly|"
        r"store.?bought|homemade|tightly packed|loosely packed|"
        r"weight after|weighed after|after removing|after skin|"
        r"at room temp|room temperature|softened|melted|packed|"
        r"leveled|sifted|whisked|beaten|drained|rinsed|"
        r"blanched|seasoned|sauteed|sauted|squeezed"
    )
    rest = re.sub(
        r"\s*,\s*[^.;]*?\b(?:" + _PREP_COMMA_PAT + r")\b[^.;]*$",
        "", rest, flags=re.I
    )

    # Strip imperative cooking instructions that sometimes follow prep notes:
    # "walnuts, shelled, break into smaller pieces to fit into the mold"
    # "chocolate, roughly chopped, melt before using"
    # "gochujang, add 1/2 Tbsp more to make it spicier"
    rest = re.sub(
        r",\s*(?:add|break|cut|place|fit|press|fold|roll|wrap|form|shape|arrange|"
        r"transfer|spread|layer|divide|crush|pound|bash|snap|melt|toast|soak)\b.*$",
        "", rest, flags=re.I
    )

    # Strip trailing variety/cultivar names after comma — they appear as Title Case
    # proper nouns: "apple , Royal Gala, Fuji" → "apple"
    # Only fires when every token after the comma is Title Case (not lowercase like
    # "free range"), so prep notes that slipped through are not affected.
    rest = re.sub(r"(\s*,\s*(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*,?\s*)+)$", "", rest)

    # Strip "e.g. X, Y" / "such as X" / "like X" variety/example clauses
    rest = re.sub(r",?\s*(?:e\.?g\.?|such as|like|i\.?e\.?)\s+.+$", "", rest, flags=re.I)

    ing_name = re.sub(r"\([^)]*\)", "", rest).strip(" ,;:")
    ing_name = re.sub(r"\s+", " ", ing_name)

    _CUT_HINT_RE = re.compile(
        r"(?:\b(?:cubed|cube|cubes|diced|dice|sliced|slice|chopped|chop|"
        r"minced|mince|grated|grate|shredded|shred|julienned|julienne)\b)\s*$",
        re.I
    )
    cut_hint = ""
    _cut_m = _CUT_HINT_RE.search(ing_name)
    if _cut_m:
        cut_hint = _cut_m.group(0).strip().lower()
        ing_name = _CUT_HINT_RE.sub("", ing_name).strip(" ,;:")

    # Strip leading prep adverbs/adjectives that ended up at the start of the name
    # e.g. "finely sliced kaffir lime" → "kaffir lime"
    #      "roughly chopped onion" → "onion"
    # Size words (medium, large, small, …) are also stripped from the search name
    # but saved as size_hint so the matcher can use them for portion label picking
    # (e.g. "medium carrot" → ingredient="carrot", size_hint="medium" →
    #  pick_best_portion receives "carrot medium" and picks the medium piece portion).
    # Loop to handle multi-word sequences like "finely sliced"
    _SIZE_WORDS = r"small|medium|large|big|jumbo|mini|tiny|giant|extra-large|extra large"
    _LEADING_PREP = (
        r"finely|thinly|roughly|coarsely|freshly|lightly|"
        r"sliced|chopped|diced|minced|grated|shredded|crushed|torn|peeled|"
        r"julienned|julienne|"
        r"frozen|dried|toasted|roasted|"
        r"lukewarm|warm|hot|cold|chilled|iced|"
        r"English|Japanese|Korean|Chinese|Thai|French|Italian|Spanish|"
        + _SIZE_WORDS
    )
    _leading_re = re.compile(r"^(?:" + _LEADING_PREP + r")\s+(?=\S)", re.I)
    _size_re    = re.compile(r"^(?:" + _SIZE_WORDS + r")\s+(?=\S)", re.I)

    # Compounds where the leading adjective is nutritionally significant and must
    # NOT be stripped — the full phrase is the ingredient identity.
    _PROTECTED_COMPOUNDS = {
        "roasted soybean", "roasted soybeans",
        "dried soybean", "dried soybeans",
        "roasted sesame", "roasted peanut", "roasted peanuts",
        "roasted garlic", "roasted tomato", "roasted tomatoes",
        "dried shrimp", "dried anchovies", "dried mushroom", "dried mushrooms",
        "dried seaweed", "dried kelp", "dried squid",
        "frozen corn", "frozen spinach", "frozen edamame",
        "toasted sesame", "toasted coconut",
    }

    # Capture the first size word before any stripping begins.
    size_hint = ""
    _size_m = _size_re.match(ing_name)
    if _size_m:
        size_hint = _size_m.group(0).strip()
    if cut_hint:
        size_hint = f"{size_hint} {cut_hint}".strip()

    # Detect "cooked" BEFORE stripping prep words — this is the caller's only
    # signal that the recipe weight is already a post-cook weight.
    # We check the name at this point (after comma/annotation stripping but
    # before leading-word removal) so "cooked pork" / "cooked rice" both fire.
    is_cooked = bool(re.search(r'\bcooked\b', ing_name, re.I))

    if ing_name.lower() not in _PROTECTED_COMPOUNDS:
        while _leading_re.match(ing_name):
            ing_name = _leading_re.sub("", ing_name).strip()

    # Strip trailing bare past-participles (no comma) left after other stripping:
    # "baking powder sifted" → "baking powder"
    # "butter melted" → "butter"  (also caught earlier but belt-and-suspenders)
    _TRAILING_BARE_PREP = re.compile(
        r"\s+(?:sifted|beaten|melted|softened|chilled|toasted|roasted|"
        r"drained|rinsed|thawed|divided|separated|cooled|warmed|"
        r"blanched|seasoned|sauteed|sauted|squeezed)\s*$", re.I
    )
    ing_name = _TRAILING_BARE_PREP.sub("", ing_name).strip()

    if not ing_name:
        return None

    # If unit is still generic (piece) or empty, check if the ingredient name
    # ends with a recognizable unit word — e.g. "salmon fillet" → unit=fillet.
    # Only do this for non-volumetric discrete units that make sense as suffixes.
    _TRAILING_UNITS = {
        "fillet": "fillet", "fillets": "fillet",
        "steak": "steak", "steaks": "steak",
        "chop": "chop", "chops": "chop",
        "drumstick": "drumstick", "drumsticks": "drumstick",
        "patty": "patty", "patties": "patty",
        "slice": "slice", "slices": "slice",
        "sheet": "sheet", "sheets": "sheet",
        "leaf": "leaf", "leaves": "leaf",
        "spear": "spear", "spears": "spear",
        "strip": "strip", "strips": "strip",
        "ear": "ear", "ears": "ear",
        "knob": "knob", "knobs": "knob",
    }
    if unit_val in (None, "piece", ""):
        words = ing_name.split()
        if words:
            last = words[-1].lower().rstrip("s")  # crude singular
            last_raw = words[-1].lower()
            matched_trailing = _TRAILING_UNITS.get(last_raw) or _TRAILING_UNITS.get(last)
            if matched_trailing and len(words) > 1:
                unit_val = matched_trailing
                ing_name = " ".join(words[:-1]).strip()

    # Re-attach inch size as a readable suffix for portion label matching.
    # e.g. "pork" + 1.5" → "pork 1.5 inch" so pick_best_portion can match
    # USDA's "1-1/2\" cube" portion label via CUBE_KEYWORDS.
    if _inch_size:
        ing_name = f"{ing_name} {_inch_size} inch"

    # "Cooking salt/kosher salt" with no qty — assign 0.01 tsp trace amount
    # and strip the "cooking" prefix so the matcher finds the right salt entry.
    _SALT_KW = ("salt", "kosher salt", "sea salt", "rock salt", "iodized salt")
    if (not qty_val and not unit_val
            and ing_name.lower().startswith("cooking")
            and any(kw in ing_name.lower() for kw in _SALT_KW)):
        clean = re.sub(r"^cooking\s+", "", ing_name, flags=re.I).strip()
        return {"qty": "0.01", "unit": "tsp", "ingredient": clean,
                "size_hint": "", "is_cooked": False, "to_taste": False, "raw": raw.strip()}

    return {
        "qty":        str(round(qty_val, 4)) if qty_val is not None else "",
        "unit":       unit_val or ("piece" if qty_val is not None else ""),
        "ingredient": ing_name,
        "size_hint":  size_hint,
        "to_taste":   False,
        "is_cooked":  is_cooked,
        "raw":        raw.strip(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# File parsing — single file, single recipe
# ═══════════════════════════════════════════════════════════════════════════════

# Separators allowed between recipe name and inline category
# "Chicken Adobo - Filipino Main"  or  "Chicken Adobo | Filipino Main"
_TITLE_CATEGORY_RE = re.compile(r"^(.+?)\s+[-|]\s+(.+)$")


def parse_single_block(lines: list[str], name_hint: str,
                       category_override: str = "",
                       sticky_category: str = "") -> tuple[dict, list[dict]]:
    """
    Parse a list of text lines as one recipe. name_hint is the filename stem.

    Category priority (highest to lowest):
      1. --category CLI flag (category_override)
      2. Inline title: "Recipe Name - Category"
      3. Sticky Category: header (sticky_category)
    """
    detected_name = None
    detected_category = ""
    detected_servings = None
    detected_aka = ""
    ingredient_lines: list[tuple[str, str]] = []   # (line, section)
    current_section = DEFAULT_SECTION

    SERVINGS_RE = re.compile(
        r"^servings?\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", re.I
    )
    AKA_RE = re.compile(r"^aka\s*[:\-]\s*(.+)$", re.I)

    for line in lines:
        stripped = re.sub(r"^#+\s*", "", line).strip()
        # Detect "--Salad" / "-- Sauce" section headers and update current_section.
        # Must check BEFORE divider/title/ingredient logic — these lines are
        # consumed entirely (not added to ingredient_lines).
        sec_m = SECTION_HEADER_RE.match(stripped)
        if sec_m and not DIVIDER_RE.match(stripped):
            current_section = sec_m.group(1).strip()
            continue
        # Detect "Servings: 30" or "Serves: 4" — skip as ingredient line
        sm = SERVINGS_RE.match(stripped)
        if sm:
            detected_servings = float(sm.group(1))
            continue
        # Detect "AKA: Name A", "Name B" — alternate names, quote-delimited
        am = AKA_RE.match(stripped)
        if am:
            detected_aka = am.group(1).strip()
            continue
        if detected_name is None and looks_like_title(stripped):
            # Try to split "Name - Category" or "Name | Category"
            m = _TITLE_CATEGORY_RE.match(stripped)
            if m:
                detected_name     = m.group(1).strip()
                detected_category = m.group(2).strip()
            else:
                detected_name = stripped
        else:
            ingredient_lines.append((line, current_section))

    recipe_name = detected_name or name_hint.replace("_", " ").title()
    # Priority: CLI flag > inline title category > sticky Category: header
    category = category_override or detected_category or sticky_category

    meta = {
        "template_id":   slugify(recipe_name),
        "template_name": recipe_name,
        "category":      category,
        "other_names":   detected_aka,
    }
    ingredients = []
    for line, sec in ingredient_lines:
        parsed = parse_ingredient_line(line)
        if parsed:
            parsed["section"] = sec
            ingredients.append(parsed)

    # Divide all quantities by servings to get per-serving amounts
    if detected_servings and detected_servings > 1:
        meta["servings"] = detected_servings
        scaled = []
        for ing in ingredients:
            if ing["qty"] and not ing["to_taste"]:
                try:
                    per_serving = float(ing["qty"]) / detected_servings
                    ing = {**ing, "qty": str(round(per_serving, 6))}
                except (ValueError, TypeError):
                    pass
            scaled.append(ing)
        ingredients = scaled

    # Expand "each" lines: "0.5 tsp each ground coriander, cumin, nutmeg"
    # → three separate rows with the same qty/unit
    expanded = []
    for ing in ingredients:
        each_match = re.match(
            r"^each\s+(.+)$", ing["ingredient"].strip(), re.I
        )
        if each_match:
            raw_parts = re.split(r",\s*|\s+and\s+", each_match.group(1))
            parts = [p.strip().strip(",;") for p in raw_parts if p.strip()]
            for part in parts:
                expanded.append({**ing, "ingredient": part})
        else:
            expanded.append(ing)
    ingredients = expanded

    # Second-pass rescue: if no title was detected and the first parsed ingredient
    # has no qty/unit and looks like a title word (e.g. "Coleslaw" from a file
    # where a blank line or BOM prevented first-pass detection), promote it.
    if not detected_name and ingredients:
        first = ingredients[0]
        if (not first["qty"] and not first["unit"] and not first["to_taste"]
                and looks_like_title(first["ingredient"].lstrip("\ufeff"))):
            candidate = first["ingredient"].lstrip("\ufeff")
            m = _TITLE_CATEGORY_RE.match(candidate)
            if m:
                detected_name     = m.group(1).strip()
                detected_category = m.group(2).strip()
            else:
                detected_name = candidate
            ingredients = ingredients[1:]
            recipe_name = detected_name
            category    = category_override or detected_category or sticky_category
            meta["template_id"]   = slugify(recipe_name)
            meta["template_name"] = recipe_name
            meta["category"]      = category
            meta.setdefault("other_names", detected_aka)
    return meta, ingredients


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-recipe file splitter
# ═══════════════════════════════════════════════════════════════════════════════

def split_into_blocks(lines: list[str]) -> list[list[str]]:
    """
    Split a list of lines into recipe blocks separated by:
      • A divider line: ---, ===, ***, ___ (3+ repeated chars)
      • 3 or more consecutive blank lines
      • A "Category: X" header line (which starts a new block and is kept)
    Single or double blank lines within a recipe are kept as-is.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    blank_run = 0

    for line in lines:
        if DIVIDER_RE.match(line):
            if any(l.strip() for l in current):
                blocks.append(current)
            current = []
            blank_run = 0
            continue

        # Category: header starts a new block, kept as first line of new block
        if CATEGORY_HEADER_RE.match(line.strip()):
            if any(l.strip() for l in current):
                blocks.append(current)
            current = [line]
            blank_run = 0
            continue

        if not line.strip():
            blank_run += 1
            if blank_run >= 3:
                if any(l.strip() for l in current):
                    blocks.append(current)
                current = []
                blank_run = 0
            else:
                current.append(line)
        else:
            blank_run = 0
            current.append(line)

    if any(l.strip() for l in current):
        blocks.append(current)

    return blocks if blocks else [lines]


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level file reader
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_HEADER_RE = re.compile(r"^category\s*[:\-]\s*(.+)$", re.I)

def parse_file(path: str, category_override: str = "") -> list[tuple[dict, list[dict]]]:
    """
    Parse a file. Returns a list of (meta, ingredients) tuples — one per recipe.
    A file with no dividers produces exactly one tuple.

    Category headers:
      A line like "Category: Japanese" sets a sticky category applied to all
      subsequent recipes until another Category: line is seen.
      The --category CLI flag overrides all category headers.
    """
    text  = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    name_hint = Path(path).stem

    blocks = split_into_blocks(lines)
    results = []
    sticky_category = ""   # carries forward across blocks

    for i, block in enumerate(blocks):
        # Check if this block is purely a Category: header (possibly with blank lines)
        non_blank = [l.strip() for l in block if l.strip()]
        if len(non_blank) == 1:
            m = CATEGORY_HEADER_RE.match(non_blank[0])
            if m:
                sticky_category = m.group(1).strip()
                continue  # not a recipe block — just update category and move on

        # If the first non-blank line of the block is a Category: header, extract
        # it and treat the rest as the recipe block.
        first_content_idx = next((j for j, l in enumerate(block) if l.strip()), None)
        if first_content_idx is not None:
            m = CATEGORY_HEADER_RE.match(block[first_content_idx].strip())
            if m:
                sticky_category = m.group(1).strip()
                block = block[first_content_idx + 1:]

        hint = name_hint if i == 0 else f"{name_hint}_{i+1}"
        meta, ingredients = parse_single_block(block, hint, category_override, sticky_category)
        if ingredients:
            results.append((meta, ingredients))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive preview
# ═══════════════════════════════════════════════════════════════════════════════

def _col(text: str, width: int, right: bool = False) -> str:
    t = str(text)[:width]
    return t.rjust(width) if right else t.ljust(width)


def preview(meta: dict, ingredients: list[dict]) -> list[dict] | None:
    """
    Print a table of parsed ingredients and let the user confirm/edit.
    Returns confirmed list, or None if the user skips this recipe entirely.
    """
    print()
    print(f"  ┌─ Recipe  : {meta['template_name']}")
    print(f"  │  ID      : {meta['template_id']}")
    print(f"  │  Category: {meta['category'] or '(none)'}")
    print(f"  └{'─'*60}")
    print()
    print(f"  {'#':>3}  {'QTY':>7}  {'UNIT':<12}  {'INGREDIENT':<36}  FLAGS")
    print(f"  {'─'*3}  {'─'*7}  {'─'*12}  {'─'*36}  {'─'*10}")

    def _print_row(i, ing):
        flag = "to taste" if ing["to_taste"] else ""
        if not ing["qty"] and not ing["to_taste"]: flag = "no qty"
        if not ing["unit"] and not ing["to_taste"]:
            flag = (flag + " no unit").strip()
        print(f"  {i:>3}  {_col(ing['qty'],7,True)}  {_col(ing['unit'],12)}  "
              f"{_col(ing['ingredient'],36)}  {flag}")

    def _print_all(rows):
        last_section = None
        for i, ing in enumerate(rows, start=1):
            sec = ing.get("section", DEFAULT_SECTION)
            if sec != last_section:
                print(f"  ── {sec} ──")
                last_section = sec
            _print_row(i, ing)

    _print_all(ingredients)

    print()
    print("  [Enter] confirm    s skip this recipe    d <n> drop row")
    print("  e <n> edit row     r rename              q quit all")
    print()

    confirmed = list(ingredients)

    while True:
        try:
            cmd = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            break  # confirm

        if cmd.lower() == "q":
            print("  Quitting.")
            sys.exit(0)

        if cmd.lower() == "s":
            print(f"  Skipped: {meta['template_name']}")
            return None

        if cmd.lower().startswith("r"):
            # rename: "r Chicken Adobo"  or just "r" to prompt
            new_name = cmd[1:].strip()
            if not new_name:
                try:
                    new_name = input(f"    name [{meta['template_name']}]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    new_name = ""
            if new_name:
                meta["template_name"] = new_name
                meta["template_id"]   = slugify(new_name)
                print(f"  Renamed → {meta['template_name']} ({meta['template_id']})")
            continue

        m = re.match(r"^d\s+(\d+)$", cmd, re.I)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(confirmed):
                print(f"  Dropped: {confirmed.pop(idx)['ingredient']}")
                _print_all(confirmed)
            else:
                print(f"  Row {idx+1} not found.")
            continue

        m = re.match(r"^e\s+(\d+)$", cmd, re.I)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(confirmed):
                ing = confirmed[idx]
                print(f"  Editing: {ing['raw']}")
                try:
                    nq = input(f"    qty  [{ing['qty']}]: ").strip()  or ing["qty"]
                    nu = input(f"    unit [{ing['unit']}]: ").strip()  or ing["unit"]
                    ni = input(f"    name [{ing['ingredient']}]: ").strip() or ing["ingredient"]
                except (EOFError, KeyboardInterrupt):
                    print(); continue
                confirmed[idx] = {**ing, "qty":nq, "unit":nu, "ingredient":ni}
                print(f"  Updated row {idx+1}.")
            else:
                print(f"  Row {idx+1} not found.")
            continue

        print("  [Enter] confirm  s skip  d <n> drop  e <n> edit  r rename  q quit")

    return confirmed


# ═══════════════════════════════════════════════════════════════════════════════
# recipes.csv writer — append-aware
# ═══════════════════════════════════════════════════════════════════════════════

FIELDNAMES = ["template_id","template_name","other_names","category","section","qty","unit","ingredient","size_hint","is_cooked"]

def write_recipes_csv(recipes: list[tuple[dict, list[dict]]], path: str, append: bool):
    """
    Write (or append) all confirmed recipes to a single recipes.csv.
    Writes the header only when creating a new file.
    """
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    mode = "a" if (append and file_exists) else "w"
    write_header = not (append and file_exists)

    total = 0
    with open(path, mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            w.writeheader()
        for meta, ingredients in recipes:
            for ing in ingredients:
                w.writerow({
                    "template_id":   meta["template_id"],
                    "template_name": meta["template_name"],
                    "other_names":   meta.get("other_names", ""),
                    "category":      meta["category"],
                    "section":       ing.get("section", DEFAULT_SECTION),
                    "qty":           ing["qty"],
                    "unit":          ing["unit"],
                    "ingredient":    ing["ingredient"],
                    "size_hint":     ing.get("size_hint", ""),
                    "is_cooked":     ing.get("is_cooked", False),
                })
                total += 1

    action = "Appended to" if (append and file_exists) else "Wrote"
    print(f"  [✓] {action} {path}  ({total} rows across {len(recipes)} recipe(s))")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        description="Parse freeform recipe(s) into recipes.csv and run matching.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python parse_recipe.py adobo.txt
  python parse_recipe.py adobo.txt sinigang.txt kare_kare.txt
  python parse_recipe.py all_recipes.txt          # auto-split on --- or 3 blank lines
  python parse_recipe.py *.txt --yes --category "Filipino Main"
  python parse_recipe.py adobo.txt --append       # add to existing templates_output.xlsx
  python parse_recipe.py adobo.txt --parse-only   # recipes.csv only, no matching
""")

    p.add_argument("inputs", nargs="+",
                   help="One or more recipe text files")
    p.add_argument("--category", "-c", default="",
                   help="Category tag applied to all recipes in this run")
    p.add_argument("--recipes-out", default="recipes.csv",
                   help="Output recipes CSV (default: recipes.csv)")
    p.add_argument("--append", action="store_true",
                   help="Append to existing recipes.csv and templates_output.xlsx "
                        "instead of overwriting (auto-enabled for multiple files)")
    p.add_argument("--parse-only", action="store_true",
                   help="Write recipes.csv only; skip matching")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip interactive preview; confirm all rows")
    p.add_argument("--force", "-f", action="store_true",
                   help="Re-run all templates in the input file even if they already exist in the output")
    p.add_argument("--forceall", action="store_true",
                   help="Skip loading existing output entirely — re-run and overwrite all templates")
    # Passthrough args for recipe_matcher.py
    p.add_argument("--boosts",        default="boosts.json")
    p.add_argument("--output",        default="templates_output.xlsx")
    p.add_argument("--threshold",     default=0.45, type=float)

    args = p.parse_args()

    # Validate inputs
    missing = [f for f in args.inputs if not os.path.exists(f)]
    if missing:
        for f in missing:
            print(f"Error: file not found: {f}", file=sys.stderr)
        sys.exit(1)

    # Auto-enable append when multiple files are given
    if len(args.inputs) > 1:
        args.append = True

    # ── parse all files ───────────────────────────────────────────────────────
    all_parsed: list[tuple[dict, list[dict]]] = []  # (meta, ingredients)
    for path in args.inputs:
        results = parse_file(path, args.category)
        n_blocks = len(results)
        label = f"{n_blocks} recipe(s)" if n_blocks > 1 else "1 recipe"
        print(f"\n[→] {path}  →  {label}")
        for meta, ingredients in results:
            print(f"    {meta['template_name']}: {len(ingredients)} ingredient lines")
        all_parsed.extend(results)

    if not all_parsed:
        print("No ingredients found. Exiting.")
        sys.exit(0)

    # ── load existing template IDs from output xlsx ───────────────────────────
    existing_tids: set[str] = set()
    xlsx_path = args.output if args.output.endswith(".xlsx") else args.output.replace(".csv", ".xlsx")
    if args.forceall:
        print(f"    --forceall active — skipping existing output, all templates will be re-run.")
        args.yes = True
    elif os.path.exists(xlsx_path):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(xlsx_path, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
                if row[0]:
                    existing_tids.add(str(row[0]).strip())
            wb.close()
            if existing_tids:
                if args.force:
                    print(f"    {len(existing_tids)} existing template ID(s) in {xlsx_path} — --force active, will re-run all.")
                else:
                    print(f"    {len(existing_tids)} existing template ID(s) in {xlsx_path} — will skip in preview (use --force to re-run).")
        except Exception as e:
            print(f"    [!] Could not read {xlsx_path}: {e}")

    total_recipes = len(all_parsed)
    print(f"\n[→] {total_recipes} recipe(s) total across {len(args.inputs)} file(s)")

    # ── preview each recipe ───────────────────────────────────────────────────
    confirmed_recipes: list[tuple[dict, list[dict]]] = []

    if args.yes:
        confirmed_recipes = all_parsed
        total_ings = sum(len(ings) for _, ings in confirmed_recipes)
        print(f"    Skipping preview (--yes). {total_ings} rows confirmed.")
    else:
        for idx, (meta, ingredients) in enumerate(all_parsed, start=1):
            tid = meta.get("template_id", "")
            if tid in existing_tids and not args.force:
                print(f"\n  ── Recipe {idx}/{total_recipes} ── {meta['template_name']} [already in output — skipping]")
                continue
            print(f"\n  ── Recipe {idx}/{total_recipes} ──────────────────────────────")
            result = preview(meta, ingredients)
            if result is None:
                print(f"  → Skipped.")
            elif not result:
                print(f"  → No rows left after edits — skipped.")
            else:
                confirmed_recipes.append((meta, result))
                print(f"  → {len(result)} rows confirmed.")

    if not confirmed_recipes:
        print("\nNothing confirmed. Exiting.")
        sys.exit(0)

    # ── write recipes.csv ─────────────────────────────────────────────────────
    write_recipes_csv(confirmed_recipes, args.recipes_out, args.append)

    if args.parse_only:
        print("  [parse-only] Done.")
        return

    # ── run recipe_matcher.py once for all recipes ────────────────────────────
    matcher = Path(__file__).parent / "recipe_matcher.py"
    if not matcher.exists():
        print(f"  [!] recipe_matcher.py not found — skipping match step.")
        return

    # If appending to xlsx, pass existing output as input too — matcher will
    # overwrite it, but the recipes.csv already has both old and new rows.
    cmd = [
        sys.executable, str(matcher),
        "--recipes",   args.recipes_out,
        "--boosts",    args.boosts,
        "--output",    args.output,
        "--threshold", str(args.threshold),
    ]
    if args.forceall:
        cmd += ["--forceall"]
    if getattr(args, "rebuild_cache", False):
        cmd += ["--rebuild-cache"]
    print(f"\n[→] Running matcher on {len(confirmed_recipes)} recipe(s) …")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
