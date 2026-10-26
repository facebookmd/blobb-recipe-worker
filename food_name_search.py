"""
Layer 1: a food name to ranked foods, and the portion its words name.

A port of the app's food search (blobb-app lib/data/search_matcher.dart and
FoodDatabase.search in food_database.dart): the same retrieval, the same
ranking, the same word lists (search_rules.json). The recipe matcher's own
recipe layer (amounts, units, cooked or raw, recipe conventions) works on
top of it. search_rank_cases.json holds the cases both implementations must
pass; a change to one side's ranking goes into the other with them.

"large banana" is bananas with the "1 large" portion: size and cut words
pick the portion. Search takes no amounts (decided 26 Oct 2026).
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

import supabase_food_source as source

RULES = json.loads(Path(__file__).with_name("search_rules.json").read_text())


def _words(section: str, key: str = "words") -> list[str]:
    return RULES[section][key]


GROUP_LABELS = set(_words("group_labels"))
SOUP_LABEL = RULES["soup_label"]["label"]
SOUP_WORDS = set(RULES["soup_label"]["query_words"])
KIND_SEGMENTS = set(_words("kind_segments"))
STANDARD_WORDS = set(_words("standard_qualifier_words"))
VARIANT_RE = re.compile(r"\b(" + "|".join(_words("variant_qualifiers", "patterns")) + r")\b")
SKINLESS_CUTS = set(RULES["skin"]["skinless_by_default_cuts"])
SKIN_ON_RE = re.compile(r"\b(" + RULES["skin"]["skin_on_pattern"] + r")\b")
PART_BREAK_RE = re.compile(" (?:" + "|".join(RULES["modifier_rules"]["part_breaks"]) + ") ")
MIX_WORDS = set(RULES["modifier_rules"]["mix_words"])
LACK_WORDS = set(RULES["modifier_rules"]["lack_words"])
PORTION_SIZES = RULES["portion_words"]["sizes"]
PORTION_CUTS = set(RULES["portion_words"]["cuts"])
PRODUCT_CUTS = set(RULES["portion_words"]["product_cuts"])
PORTION_FILLERS = set(RULES["portion_words"]["fillers"])
STATE_WORDS = set(_words("state_words"))
FRESH_IS_RAW = {"fresh", "raw"}
WITH_LEAD = RULES["with_qualifiers"]["lead"]
WITH_IGNORED = set(RULES["with_qualifiers"]["ignore"])
PART_SEGMENTS = set(_words("part_segments"))

NOT_SPECIFIED_RE = re.compile(r"\b(nfs|ns as to)\b")

UNKNOWN_QUALIFIER_PENALTY = 80
VARIANT_PENALTY = 250
DESCRIBES_PENALTY = 60
NO_ENERGY_PENALTY = 300
# A match on a row's category, brand owner, scientific name or barcode only
# ranks this much below one on its name: brand "Star Anise Foods" put
# "BROWN RICE NOODLES" above "STAR ANISE" (26 Oct 2026).
OTHER_FIELD_PENALTY = 100

USDA_CANDIDATE_LIMIT = 500
HEAD_CANDIDATE_LIMIT = 100


# ── Text ────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def tokens(text: str) -> list[str]:
    n = normalize(text)
    return n.split(" ") if n else []


def canonical(token: str) -> str:
    t = token.lower().strip()
    if len(t) <= 3:
        return t
    if t == "powdered":
        return "powder"
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith(("oes", "ches", "shes", "xes", "zes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def alias_key(text: str) -> str:
    """foodAliasKey / template_key: normalized, each word singular."""
    out = []
    for w in normalize(text).split():
        if len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def _strip_parentheses(text: str) -> str:
    return re.sub(r"\([^)]*\)", "", text)


@dataclass(frozen=True)
class Query:
    raw: str
    normalized: str
    tokens: tuple[str, ...]

    @staticmethod
    def parse(text: str) -> "Query":
        raw = (text or "").strip()
        n = normalize(raw)
        seen: list[str] = []
        for t in n.split(" ") if n else []:
            if t and t not in seen:
                seen.append(t)
        return Query(raw, n, tuple(seen))

    @property
    def empty(self) -> bool:
        return not self.normalized


# ── Portion words ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SplitQuery:
    """A search split into the food's words and the words naming a portion:
    "large banana" is "banana" and ("large",)."""
    food: str
    portion_words: tuple[str, ...]

    @property
    def product_cuts(self) -> tuple[str, ...]:
        """Portion words that can also name the product ("mashed")."""
        return tuple(w for w in self.portion_words if w in PRODUCT_CUTS)


def split_portion_words(text: str) -> SplitQuery:
    """Sizes and cut words leave the food's words and pick the portion;
    fillers ("finely") just leave. A search of nothing but such words is
    searched whole."""
    n = normalize(text)
    for size in sorted(PORTION_SIZES, key=len, reverse=True):
        n = re.sub(rf"\b{size}\b", "__" + size.replace(" ", "_") + "__", n)
    food, portion = [], []
    for w in n.split():
        if w.startswith("__") and w.endswith("__"):
            portion.append(w.strip("_").replace("_", " "))
        elif w in PORTION_CUTS:
            portion.append(w)
        elif w not in PORTION_FILLERS:
            food.append(w)
    if not food:
        return SplitQuery(normalize(text), ())
    return SplitQuery(" ".join(food), tuple(portion))


def preferred_portion(labels: list[str], portion_words: tuple[str, ...]) -> int | None:
    """The index of the first portion (in USDA's order) whose label names a
    portion word: "1 large (8\" to 8-7/8\" long)" for "large", "1 cup,
    sliced" for "sliced". Sizes before cuts. None when none does."""
    for word in sorted(portion_words, key=lambda w: w not in PORTION_SIZES):
        for i, label in enumerate(labels):
            if re.search(rf"\b{re.escape(word)}\b", normalize(label)):
                # "large" isn't "extra large".
                if word == "large" and re.search(r"\bextra large\b", normalize(label)):
                    continue
                return i
    return None


# ── Ranks ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rank:
    tier: int = 0
    bucket: int = 0
    matched: int = 0
    exact: int = 0
    near_exact: int = 0
    prefix: int = 0
    fuzzy: int = 0
    head_strength: int = 0
    word_count: int = 0
    length: int = 0

    @property
    def is_match(self) -> bool:
        return (self.tier > 0 or self.bucket > 0 or self.matched > 0 or self.exact > 0
                or self.near_exact > 0 or self.prefix > 0 or self.fuzzy > 0)

    def key(self) -> tuple:
        return (self.tier, self.bucket, self.matched, self.exact, self.near_exact,
                self.prefix, self.fuzzy, self.head_strength, -self.word_count, -self.length)

    def penalized(self, amount: int) -> "Rank":
        if amount <= 0 or not self.is_match:
            return self
        return replace(self, bucket=self.bucket - amount)

    def demoted(self) -> "Rank":
        if not self.is_match:
            return self
        return replace(self, tier=1, bucket=self.bucket - 1000)


NONE = Rank()


def _build_rank(tier, bucket, matched, exact, near, prefix, fuzzy, head, cand_tokens) -> Rank:
    return Rank(tier, bucket, matched, exact, near, prefix, fuzzy, head,
                len(cand_tokens), sum(len(t.strip()) for t in cand_tokens))


# ── Display-name ranking (SearchScorer) ─────────────────────────────────────

@dataclass
class _Parts:
    head_tokens: list[str]
    full_tokens: list[str]


def _split_display_parts(text: str, comma_head: bool) -> _Parts:
    t = text.strip()
    if not t:
        return _Parts([], [])
    if comma_head and "," in t:
        head = t[:t.index(",")].strip()
        head_tokens = tokens(head)
        return _Parts(head_tokens or tokens(t), tokens(t))
    toks = tokens(t)
    return _Parts(toks, toks)


def _is_plural_variant(q: str, c: str) -> bool:
    if not q or not c:
        return False
    if c == q + "s":
        return True
    if len(q) > 1 and q.endswith("y") and q[-2] not in "aeiou" and c == q[:-1] + "ies":
        return True
    return False


@dataclass
class _Summary:
    matched: int = 0
    matched_cand: int = 0
    exact: int = 0
    plural: int = 0
    head_matched: int = 0


def _match_tokens(q_tokens, c_tokens, head_count=0, allow_plural=True) -> _Summary:
    used: set[int] = set()
    s = _Summary()
    for qt in q_tokens:
        best, plural = -1, False
        for i, ct in enumerate(c_tokens):
            if i not in used and ct == qt:
                best = i
                break
        if best < 0 and allow_plural:
            for i, ct in enumerate(c_tokens):
                if i not in used and _is_plural_variant(qt, ct):
                    best, plural = i, True
                    break
        if best < 0:
            continue
        used.add(best)
        s.matched += 1
        s.matched_cand += 1
        if plural:
            s.plural += 1
        else:
            s.exact += 1
        if best < head_count:
            s.head_matched += 1
    return s


def _extra_words(cand_tokens, matched_cand) -> int:
    return max(0, len(cand_tokens) - matched_cand)


def _structured_rank(tier, base, summary: _Summary, cand_tokens) -> Rank:
    bucket = (base + summary.exact * 2 + summary.plural + summary.head_matched * 3
              - _extra_words(cand_tokens, summary.matched_cand) * 20)
    return _build_rank(tier, bucket, summary.matched, summary.exact, summary.plural, 0, 0,
                       summary.head_matched, cand_tokens)


def _bounded_exact(a, b) -> bool:
    if len(a) != len(b):
        return False
    rest = list(b)
    for t in a:
        if t not in rest:
            return False
        rest.remove(t)
    return not rest


def _is_tier1(q_tokens, parts: _Parts, order_insensitive: bool) -> bool:
    if not q_tokens or not parts.full_tokens:
        return False
    if order_insensitive:
        if _bounded_exact(q_tokens, parts.head_tokens):
            return True
        if len(q_tokens) == 1 and len(parts.head_tokens) == 1:
            s = _match_tokens(q_tokens, parts.head_tokens, len(parts.head_tokens), True)
            return s.plural == 1 and s.matched == 1
        return False
    s = _match_tokens(q_tokens, parts.full_tokens, len(parts.head_tokens), False)
    if s.matched == len(q_tokens) and s.exact == len(q_tokens):
        return True
    if len(q_tokens) == 1:
        s = _match_tokens(q_tokens, parts.full_tokens, len(parts.head_tokens), True)
        return s.plural == 1 and s.matched == 1
    return False


def _structured_tier1(q_tokens, parts: _Parts, order_insensitive: bool) -> Rank:
    if not q_tokens or not parts.full_tokens:
        return NONE
    if order_insensitive:
        if _bounded_exact(q_tokens, parts.head_tokens):
            s = _match_tokens(q_tokens, parts.head_tokens, len(parts.head_tokens), False)
            return _structured_rank(3, 1000, s, parts.full_tokens)
        if len(q_tokens) == 1 and len(parts.head_tokens) == 1:
            s = _match_tokens(q_tokens, parts.head_tokens, len(parts.head_tokens), True)
            if s.plural == 1 and s.matched == 1:
                return _structured_rank(3, 990, s, parts.full_tokens)
        return NONE
    s = _match_tokens(q_tokens, parts.full_tokens, len(parts.head_tokens), False)
    if s.matched == len(q_tokens) and s.exact == len(q_tokens):
        return _structured_rank(3, 1000, s, parts.full_tokens)
    if len(q_tokens) == 1:
        s = _match_tokens(q_tokens, parts.full_tokens, len(parts.head_tokens), True)
        if s.plural == 1 and s.matched == 1:
            return _structured_rank(3, 990, s, parts.full_tokens)
    return NONE


def _structured_tier2(q_tokens, parts: _Parts, order_insensitive: bool) -> Rank:
    if not q_tokens or not parts.full_tokens:
        return NONE
    if _is_tier1(q_tokens, parts, order_insensitive):
        return NONE
    s = _match_tokens(q_tokens, parts.full_tokens, len(parts.head_tokens), True)
    if s.matched != len(q_tokens) or s.head_matched == 0:
        return NONE
    return _structured_rank(2, 700, s, parts.full_tokens)


def _food_before_break(q_tokens, name: str) -> bool:
    """Whether the query's food (its last word) is in *name* before any
    "with", "in" or "on": "Gluten-free white bread with potato extract, rice
    starch" isn't potato starch."""
    before = tokens(PART_BREAK_RE.split(normalize(name), 1)[0])
    return _match_tokens(list(q_tokens[-1:]), before, len(before), True).matched > 0


def _edit_distance(a: str, b: str, max_d: int) -> int:
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        row_min = i
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            row_min = min(row_min, v)
        if row_min > max_d:
            return max_d + 1
        prev = cur
    return prev[len(b)]


def _term_score(q: str, c: str, allow_plural=True) -> float:
    if q == c:
        return 1.0
    if allow_plural and _is_plural_variant(q, c):
        return 0.98
    if c.startswith(q):
        extra = len(c) - len(q)
        return 0.92 if extra <= 1 else 0.88 if extra <= 3 else 0.84
    if q.startswith(c):
        extra = len(q) - len(c)
        return 0.90 if extra <= 1 else 0.84 if extra <= 3 else 0.78
    d = _edit_distance(q, c, 2)
    return 0.72 if d == 1 else 0.55 if d == 2 else 0.0


def _general_rank(query: Query, text: str, allow_plural=True) -> Rank:
    cand = tokens(text)
    if not cand or not query.tokens:
        return NONE
    used: set[int] = set()
    matched = exact = near = prefix = fuzzy = 0
    for qt in query.tokens:
        qt = qt.strip()
        if not qt:
            continue
        best_score, best_i = 0.0, -1
        for i, ct in enumerate(cand):
            if i in used or not ct.strip():
                continue
            sc = _term_score(qt, ct.strip(), allow_plural)
            if sc > best_score:
                best_score, best_i = sc, i
                if sc == 1.0:
                    break
        if best_score <= 0.0:
            continue
        used.add(best_i)
        matched += 1
        if best_score >= 1.0:
            exact += 1
        elif best_score >= 0.95:
            near += 1
        elif best_score >= 0.84:
            prefix += 1
        else:
            fuzzy += 1
    if matched == 0:
        return NONE
    head = 0
    head_token = cand[0].strip()
    if head_token:
        for qt in query.tokens:
            sc = _term_score(qt.strip(), head_token, allow_plural)
            if sc >= 1.0:
                head = 3
                break
            if sc >= 0.95 and head < 2:
                head = 2
            elif sc > 0.0 and head < 1:
                head = 1
    extra = _extra_words(cand, matched)
    bucket = 400 + exact * 12 + near * 8 + prefix * 4 + fuzzy * 2 + head * 3 - extra * 2
    return _build_rank(1, bucket, matched, exact, near, prefix, fuzzy, head, cand)


def rank_usda_display_name(query: Query, name: str, branded=False) -> Rank:
    cleaned = (name or "").strip()
    if query.empty or not cleaned:
        return NONE
    if not branded:
        parts = _split_display_parts(cleaned, True)
        r = _structured_tier1(list(query.tokens), parts, True)
        if not r.is_match:
            r = _structured_tier2(list(query.tokens), parts, True)
            if r.is_match and not _food_before_break(query.tokens, cleaned):
                r = NONE
        if r.is_match:
            return r
    return _general_rank(query, cleaned, allow_plural=not branded)


def rank_fields(query: Query, candidates) -> Rank:
    best = NONE
    for c in candidates:
        r = rank_usda_display_name(query, c) if (c or "").strip() else NONE
        if r.key() > best.key():
            best = r
    return best


def rank_general_fields(query: Query, candidates, allow_plural=True) -> Rank:
    best = NONE
    for c in candidates:
        r = _general_rank(query, c.strip(), allow_plural) if (c or "").strip() else NONE
        if r.key() > best.key():
            best = r
    return best


# ── USDA description rules ──────────────────────────────────────────────────

def usda_segments(description: str) -> list[str]:
    d = re.sub(r"\((?:includes|formerly|for use|also)[^)]*\)", "", description or "", flags=re.I)
    d = re.sub(r"\(([^)]*)\)", r", \1", d)
    return [s.strip() for s in d.split(",") if s.strip()]


def usda_head_qualifiers(query: Query, description: str) -> list[str] | None:
    segs = usda_segments(description)
    if not segs or query.empty:
        return None
    found = _head_qualifiers(list(query.tokens), segs)
    if found is not None:
        return found
    # A state word before the food, in a qualifier (search_rules.json
    # state_words): "frozen peas" is "Peas, green, frozen, unprepared".
    state = {canonical(t) for t in query.tokens if t in STATE_WORDS}
    rest = [t for t in query.tokens if t not in STATE_WORDS]
    if not state or not rest:
        return None
    found = _head_qualifiers(rest, segs)
    if found is None:
        return None
    # Fresh is raw: "fresh tomatoes" is "Tomatoes, red, ripe, raw".
    said = state | (FRESH_IS_RAW if state & FRESH_IS_RAW else set())
    if not state - FRESH_IS_RAW <= {canonical(t) for q in found for t in tokens(q)}:
        return None
    if state & FRESH_IS_RAW and not FRESH_IS_RAW & {canonical(t) for q in found for t in tokens(q)}:
        return None
    return [q for q in found if not {canonical(t) for t in tokens(q)} <= said]


def _or_head(segment: str) -> list[str] | None:
    """The head before a one-word alternative name: "Beef broth or
    bouillon" is beef broth. Not another food: "Bacon or side pork"."""
    parts = normalize(segment).split(" or ")
    if len(parts) == 2 and len(parts[1].split()) == 1:
        return [canonical(t) for t in parts[0].split()]
    return None


def _head_qualifiers(query_tokens: list[str], segs: list[str]) -> list[str] | None:
    wanted_order = [canonical(t) for t in query_tokens]
    wanted_sorted = sorted(wanted_order)

    def head_of(s):
        if not s:
            return None
        if [canonical(t) for t in tokens(s[0])] == wanted_order or _or_head(s[0]) == wanted_order:
            return s[1:]
        if len(s) > 1 and sorted(canonical(t) for t in tokens(f"{s[0]} {s[1]}")) == wanted_sorted:
            return s[2:]
        return None

    direct = head_of(segs)
    if direct is not None:
        return direct
    label = normalize(segs[0])
    if len(segs) > 1 and (label in GROUP_LABELS or (
            label == SOUP_LABEL and any(t in SOUP_WORDS for t in wanted_order))):
        return head_of(segs[1:])
    if len(segs) > 2 and normalize(segs[1]) in KIND_SEGMENTS:
        return head_of([segs[0], *segs[2:]])
    return None


def usda_row_head_qualifiers(query: Query, description: str, display_name: str) -> list[str] | None:
    q = usda_head_qualifiers(query, description)
    if q is None and (display_name or "").strip():
        q = usda_head_qualifiers(query, display_name)
    return q


def usda_variant_count(query: Query, description: str) -> int:
    if query.empty:
        return 0
    n = normalize(description)
    wanted = {canonical(t) for t in query.tokens}
    present = {canonical(t) for t in tokens(n)}
    if not wanted <= present:
        return 0
    hits = {m.group(0) for m in VARIANT_RE.finditer(n)}
    hits = {h for h in hits if not any(canonical(w) in wanted for w in h.split(" "))}
    skin_on = bool(wanted & SKINLESS_CUTS) and "skin" not in wanted and bool(SKIN_ON_RE.search(n))
    return len(hits) + skin_on


def part_segment_count(query: Query, qualifiers: list[str]) -> int:
    """Head qualifiers naming only a part of the food that the query doesn't
    say (search_rules.json part_segments): "skin" of "Potatoes, raw, skin"."""
    said = {canonical(t) for t in query.tokens}
    return sum(1 for q in qualifiers
               if normalize(q) in PART_SEGMENTS and canonical(normalize(q)) not in said)


def with_food_count(query: Query, qualifiers: list[str]) -> int:
    """Head qualifiers "with ..." naming another food the query doesn't say
    (search_rules.json with_qualifiers): "with potatoes" of "Chicken, fried,
    with potatoes, vegetable, frozen meal"."""
    said = {canonical(t) for t in query.tokens}
    count = 0
    for q in qualifiers:
        words = tokens(q)
        if len(words) < 2 or words[0] != WITH_LEAD:
            continue
        other = [w for w in words[1:] if w not in STANDARD_WORDS and w not in WITH_IGNORED
                 and not w.isdigit()]
        if other and not any(canonical(w) in said for w in other):
            count += 1
    return count


def is_unknown_qualifier(segment: str) -> bool:
    n = normalize(segment)
    if not n or VARIANT_RE.search(n):
        return False
    return not all(t in STANDARD_WORDS or t.isdigit() for t in n.split(" "))


def is_not_specified(description: str) -> bool:
    return bool(NOT_SPECIFIED_RE.search(normalize(description)))


def query_modifies(query: Query, name: str) -> str:
    """"none", "describes" or "mix_or_lacks" (queryModifies)."""
    if query.empty:
        return "none"
    wanted = [canonical(t) for t in query.tokens]
    last = wanted[-1]
    words = [canonical(t) for t in tokens(_strip_parentheses(name))]
    for i in range(len(words) - 1):
        if words[i] in LACK_WORDS and words[i + 1] in wanted:
            return "mix_or_lacks"
    segments = [PART_BREAK_RE.split(normalize(s)) for s in _strip_parentheses(name).split(",")]

    def toks(t):
        return [canonical(x) for x in tokens(t)]

    head = toks(segments[0][0])
    for i in range(1, len(head) - 1):
        if head[i] in MIX_WORDS and (head[i - 1] in wanted) != (head[i + 1] in wanted):
            return "mix_or_lacks"
    if len(wanted) > 1 and any(head[i:i + len(wanted)] == wanted for i in range(len(head))):
        return "none"
    if len(head) >= 2 and last in head and head[-1] != last:
        return "describes"
    before = [t for parts in segments for t in toks(parts[0])]
    after = [t for parts in segments for part in parts[1:] for t in toks(part)]
    if last not in before and last in after:
        return "describes"
    return "none"


def rank_usda_row(query: Query, display_rank: Rank, description: str, display_name: str,
                  is_foundation: bool, has_calories: bool) -> Rank:
    if query.empty or not (description or "").strip():
        return display_rank
    rank = display_rank
    quals = usda_row_head_qualifiers(query, description, display_name)
    penalty = usda_variant_count(query, description) * VARIANT_PENALTY
    if quals is not None:
        unknown = sum(is_unknown_qualifier(q) for q in quals)
        rank = _build_rank(4, 1000 - unknown * UNKNOWN_QUALIFIER_PENALTY, len(query.tokens),
                           len(query.tokens), 0, 0, 0, 3, tokens(_strip_parentheses(description)))
        penalty += (part_segment_count(query, quals) + with_food_count(query, quals)) * VARIANT_PENALTY
    if is_foundation and not has_calories:
        penalty += NO_ENERGY_PENALTY
    return rank.penalized(penalty)


def demote_modifier_match(query: Query, rank: Rank, name: str) -> Rank:
    if rank.tier >= 4:
        return rank
    m = query_modifies(query, name)
    if m == "describes":
        return rank.penalized(DESCRIBES_PENALTY)
    if m == "mix_or_lacks":
        return rank.demoted()
    return rank


# ── Rows (FoodDatabase._scoreUsdaRow) ───────────────────────────────────────

def _text(v) -> str:
    return "" if v is None else str(v).strip()


def is_branded_row(row: dict) -> bool:
    return _text(row.get("source_set")).lower() == "branded"


def score_row(query: Query, row: dict) -> Rank:
    branded = is_branded_row(row)
    display = _text(row.get("display_name"))
    display_rank = (rank_usda_display_name(query, display, branded=True) if branded
                    else rank_usda_display_name(query, display))
    rank = display_rank
    if not rank.is_match:
        # The description is a name too; the other fields only say who
        # makes it or where it's filed (OTHER_FIELD_PENALTY).
        def fields_rank(fields):
            return (rank_general_fields(query, fields, allow_plural=False) if branded
                    else rank_fields(query, fields))
        rank = fields_rank([_text(row.get("description"))])
        other = fields_rank([_text(row.get(k)) for k in ("category", "brand_owner",
                                                         "scientific_name", "gtin_upc")])
        other = other.penalized(OTHER_FIELD_PENALTY)
        if other.key() > rank.key():
            rank = other
    if not branded:
        cal = row.get("calories_100g")
        rank = rank_usda_row(query, rank, _text(row.get("description")), display,
                             _text(row.get("data_type")).lower() == "foundation",
                             isinstance(cal, (int, float)) and cal > 0)
    return demote_modifier_match(query, rank, display)


def names_product_cut(query: Query, row: dict, cuts: tuple[str, ...]) -> bool:
    """A USDA row headed by the food that says one of *cuts*: "Potatoes,
    mashed, ..." for "mashed potatoes"."""
    if not cuts or is_branded_row(row):
        return False
    desc, display = _text(row.get("description")), _text(row.get("display_name"))
    if usda_row_head_qualifiers(query, desc, display) is None:
        return False
    named = set(tokens(f"{desc} {display}"))
    return any(c in named for c in cuts)


def rank_rows(query: Query, rows: list[dict], alias_row_id: int | None = None,
              product_cuts: tuple[str, ...] = ()) -> list[dict]:
    """FoodDatabase._rankedRowSet's order: an alias's food first, then a USDA
    row naming the search's product cut ([names_product_cut]), then by rank,
    display name and id. USDA's "not further specified" rows go."""
    kept = [r for r in rows if is_branded_row(r) or not is_not_specified(_text(r.get("description")))]
    scored = [(r, score_row(query, r), names_product_cut(query, r, product_cuts)) for r in kept]

    def cmp(a, b):
        aa = 1 if alias_row_id is not None and a[0].get("id") == alias_row_id else 0
        ba = 1 if alias_row_id is not None and b[0].get("id") == alias_row_id else 0
        if aa != ba:
            return ba - aa
        if a[2] != b[2]:
            return -1 if a[2] else 1
        if a[1].key() != b[1].key():
            return -1 if a[1].key() > b[1].key() else 1
        na, nb = _text(a[0].get("display_name")).lower(), _text(b[0].get("display_name")).lower()
        if na != nb:
            return -1 if na < nb else 1
        return (int(a[0].get("id") or 0) > int(b[0].get("id") or 0)) - (
            int(a[0].get("id") or 0) < int(b[0].get("id") or 0))

    return [r for r, _, _ in sorted(scored, key=functools.cmp_to_key(cmp))]


# ── Retrieval (FoodDatabase.search) ─────────────────────────────────────────

_SELECT = quote(source._FOOD_SEARCH_SELECT)
_ALIASES: dict[str, int] | None = None


def _rest(params: str) -> str:
    return f"{source._supabase_url()}/rest/v1/{params}"


def _food_aliases() -> dict[str, int]:
    global _ALIASES
    if _ALIASES is None:
        rows = source._request_all([("food alias lookup", _rest("food_aliases?select=alias,food_id"))])[0]
        _ALIASES = {alias_key(r["alias"]): int(r["food_id"]) for r in rows if r.get("food_id")} if rows else {}
    return _ALIASES


def fetch_rows(food_words: str, limit: int = 60, alias_text: str | None = None) -> tuple[list[dict], int | None]:
    """The rows the app's search fetches for *food_words*, and the row id its
    alias names (None): full text over all sources and over USDA rows alone,
    USDA rows named the query outright (and branded ones named with it, for
    a query of several words), and a substring pass when full text came back
    short."""
    q = Query.parse(food_words)
    if q.empty:
        return [], None
    candidate_limit = limit * 4
    tsq = " & ".join(f"{t}:*" for t in q.tokens)
    n = q.normalized
    head_or = [f'description.ilike."{n},*"', f'description.ilike."{n}"',
               f'display_name.ilike."{n},*"', f'display_name.ilike."{n}"']
    # Rows headed by the food without its state words: full text needs
    # "fresh", which "Tomatoes, red, ripe, raw" never says.
    rest = " ".join(t for t in q.tokens if t not in STATE_WORDS)
    if rest and rest != n:
        head_or += [f'description.ilike."{rest},*"', f'display_name.ilike."{rest},*"']
    if " " in n:
        head_or.append(f'display_name.ilike."*{n}*"')
    reqs = [
        ("full-text search", _rest(f"foods?select={_SELECT}&search_vector=fts(english).{quote(tsq)}"
                                   f"&calories_100g=not.is.null&limit={candidate_limit}")),
        ("USDA full-text search", _rest(f"foods?select={_SELECT}&search_vector=fts(english).{quote(tsq)}"
                                        f"&calories_100g=not.is.null&source_set=neq.branded"
                                        f"&limit={USDA_CANDIDATE_LIMIT}")),
        ("exact name search", _rest(f"foods?select={_SELECT}&or=({quote(','.join(head_or))})"
                                    f"&source_set=neq.branded&calories_100g=not.is.null"
                                    f"&limit={HEAD_CANDIDATE_LIMIT}")),
    ]
    if " " in n:
        # Branded products named with the search ("SMOKED PAPRIKA", "TASTY
        # JOY, SUGAR PALM FRUIT"): full text over every source fills its
        # rows with products that only list them as ingredients. Narrowed by
        # full text: a name pattern alone times out over the branded rows.
        # Named exactly apart: hundreds of products contain "white vinegar",
        # and the plain "WHITE VINEGAR" fell outside those fetched.
        for what, pattern in (("branded exact name search", n), ("branded name search", f"*{n}*")):
            reqs.append((what, _rest(
                f"foods?select={_SELECT}&search_vector=fts(english).{quote(' & '.join(q.tokens))}"
                f"&display_name=ilike.{quote(pattern)}&source_set=eq.branded"
                f"&calories_100g=not.is.null&limit={HEAD_CANDIDATE_LIMIT}")))
    all_rows, usda_rows, head_rows, *branded_named = source._request_all(reqs)
    by_id = {r["id"]: r for r in [*all_rows, *usda_rows, *head_rows, *(r for rows in branded_named for r in rows)]}
    if len(all_rows) < candidate_limit:
        pattern = "*" + n.replace("%", "").replace("*", "") + "*"
        fb = source._request_all([("substring search", _rest(
            f"foods?select={_SELECT}&or=({quote(f'description.ilike.{pattern},display_name.ilike.{pattern}')})"
            f"&calories_100g=not.is.null&limit={candidate_limit}"))])[0]
        for r in fb:
            by_id.setdefault(r["id"], r)
    aliases = _food_aliases()
    alias_id = aliases.get(alias_key(alias_text)) if alias_text else None
    if alias_id is None:
        alias_id = aliases.get(alias_key(food_words))
    if alias_id is not None and alias_id not in by_id:
        rows = source._request_all([("alias food", _rest(
            f"foods?select={_SELECT}&id=eq.{alias_id}&calories_100g=not.is.null&limit=1"))])[0]
        for r in rows:
            by_id[r["id"]] = r
    return list(by_id.values()), (alias_id if alias_id in by_id else None)


def search(text: str, limit: int = 60) -> tuple[list[dict], SplitQuery]:
    """Ranked rows for a search, best first, and how it was split."""
    split = split_portion_words(text)
    # An alias names the whole search ("hot sauce"), else the food's words.
    rows, alias_id = fetch_rows(split.food, limit, alias_text=text)
    ranked = rank_rows(Query.parse(split.food), rows, alias_id, split.product_cuts)
    return ranked[:limit], split
