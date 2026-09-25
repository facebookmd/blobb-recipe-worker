#!/usr/bin/env python3
"""
ai_matcher.py
-------------
Second-pass resolver for ingredients that recipe_matcher.py couldn't match
confidently. Uses the Claude API to identify the correct USDA entry and
writes permanent boost rules to boosts.json.

WORKFLOW
  1. Run recipe_matcher.py as normal → templates_output.csv
  2. Run ai_matcher.py → resolves pink/amber rows, appends to boosts.json
  3. Re-run recipe_matcher.py --boosts boosts.json → clean output

USAGE
  python ai_matcher.py
      --debug-csv  templates_output_debug.csv   # the _debug.csv from matcher
      --boosts     boosts.json                  # appended to, not overwritten
      [--dry-run]                               # print proposed rules, don't save
      [--only-none]                             # only fix unmatched (pink), skip low conf (amber)

REQUIREMENTS
  pip install anthropic
  Set ANTHROPIC_API_KEY environment variable.

BOOST RULE SCHEMA (written to boosts.json)
  Each rule is one of:

  Standard boost — redirect ingredient to a better search string:
    {"trigger": "cooking sake", "boost": "sake", "weight": 0.9}

  With exclude — only fire if these substrings are NOT in the ingredient:
    {"trigger": "mirin", "boost": "mirin sweet cooking rice wine",
     "weight": 0.9, "exclude": ["extract", "flavour"]}
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

from supabase_food_source import (
    is_configured as supabase_is_configured,
    load_food_rows as load_supabase_food_rows,
)

# ── Config ────────────────────────────────────────────────────────────────────

MODEL          = "claude-sonnet-4-20250514"
MAX_TOKENS     = 1024
MAX_CANDIDATES = 30      # USDA candidates sent to Claude per ingredient
RETRY_DELAY    = 2.0     # seconds between API calls to avoid rate limits

# ── USDA loader (minimal — just names and fdc_ids) ────────────────────────────

def load_usda_names() -> list[dict]:
    """Load food display names and alt names from Supabase."""
    if not supabase_is_configured():
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_ANON_KEY "
            "(and optionally SUPABASE_URL) environment variables."
        )

    foods = []
    for row in load_supabase_food_rows(source_set="usda"):
        display_name = str(row.get("display_name") or row.get("description") or "").strip()
        if not display_name:
            continue
        alt_names = []
        for candidate in (
            row.get("ingredients"),
            row.get("scientific_name"),
            row.get("brand_owner"),
            row.get("category"),
            row.get("household_serving_full_text"),
        ):
            text = str(candidate or "").strip()
            if text and text not in alt_names:
                alt_names.append(text)
        payload = row.get("payload")
        if isinstance(payload, dict):
            for key in ("foodCategory", "brandedFoodCategory"):
                text = str(payload.get(key) or "").strip()
                if text and text not in alt_names:
                    alt_names.append(text)
        foods.append({
            "fdc_id": str(row.get("fdc_id") or ""),
            "display_name": display_name,
            "alt_names": alt_names,
        })
    return foods


# ── Candidate finder (simple substring/token overlap) ────────────────────────

def _tokens(text: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
            if len(t) >= 2}


def find_usda_candidates(ingredient: str, usda_foods: list,
                         n: int = MAX_CANDIDATES) -> list[dict]:
    """Return up to n USDA foods whose names share tokens with ingredient."""
    ing_tokens = _tokens(ingredient)
    scored = []
    for food in usda_foods:
        name_tokens = _tokens(food["display_name"])
        alt_tokens  = set()
        for alt in food.get("alt_names", []):
            alt_tokens |= _tokens(alt)
        overlap = len(ing_tokens & (name_tokens | alt_tokens))
        if overlap:
            scored.append((overlap, food))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:n]]


# ── Claude prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a nutrition database expert helping match recipe ingredients to USDA food entries.

You will be given one of two tasks:

TASK A — MATCHING: ingredient has no good match or a weak match.
You will see the ingredient name and candidate food entries.
Return a boost rule to fix the matching.

RULE TYPES:

Matching boost:
  {"trigger": "cooking sake", "boost": "sake", "weight": 0.9}

Boost with exclusions:
  {"trigger": "mirin", "boost": "mirin sweet cooking rice wine", "weight": 0.9, "exclude": ["extract"]}

null — ingredient genuinely has no match in either database

Rules:
- "trigger" must be a substring of the ingredient name (lowercase)
- "boost" must be a substring of the USDA display_name
- For portion overrides: portion_gram_weight is the gram weight of the RECIPE quantity
  (e.g. if recipe uses 0.75 tbsp mirin, and 1 tbsp mirin = 18g, then 0.75 tbsp = 13.5g)
- Use real culinary knowledge for densities — oils ~0.9g/ml, syrups/sauces ~1.2-1.4g/ml,
  dry powders vary widely
- Return ONLY valid JSON, no explanation, no markdown fences"""


def build_user_prompt(ingredient: str, usda_candidates: list) -> str:
    lines = [f'Ingredient: "{ingredient}"', "", "USDA candidates:"]
    for i, food in enumerate(usda_candidates, 1):
        alts = f" | alts: {', '.join(food['alt_names'][:2])}" if food.get("alt_names") else ""
        lines.append(f"  {i}. [{food['fdc_id']}] {food['display_name']}{alts}")

    lines += [
        "",
        "Return a single JSON boost rule object, or null if no fix is possible.",
        "Examples:",
        '  {"trigger": "cooking sake", "boost": "sake", "weight": 0.9}',
        '  {"trigger": "mirin", "boost": "mirin sweet cooking rice wine", "weight": 0.9}',
        "  null",
    ]
    return "\n".join(lines)


# ── Claude API call ───────────────────────────────────────────────────────────

def resolve_with_claude(client: anthropic.Anthropic,
                        ingredient: str,
                        usda_candidates: list) -> dict | None:
    """Call Claude and parse the returned boost rule. Returns None on failure."""
    prompt = build_user_prompt(ingredient, usda_candidates)
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if Claude added them despite instructions
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        if raw.lower() == "null":
            return None
        rule = json.loads(raw)
        # Validate minimum required fields
        if "trigger" not in rule:
            return None
        if "boost" not in rule:
            return None
        return rule
    except (json.JSONDecodeError, anthropic.APIError, IndexError) as e:
        print(f"    [!] Claude error for '{ingredient}': {e}")
        return None


# ── Debug CSV reader ──────────────────────────────────────────────────────────

def load_problem_ingredients(debug_csv: str,
                             only_none: bool = False) -> list[dict]:
    """
    Read templates_output_debug.csv and return ingredients that need fixing:
      - _confidence == "none"  (unmatched, shown pink in xlsx)
      - _confidence == "low"   (weak match, shown amber) — unless only_none

    Deduplicates by component_label so each unique ingredient string is only
    sent to Claude once, even if it appears in multiple templates.
    """
    seen: set[str] = set()
    problems: list[dict] = []

    if not os.path.exists(debug_csv):
        print(f"Error: debug CSV not found: {debug_csv}")
        sys.exit(1)

    with open(debug_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conf  = row.get("_confidence", "").strip()
            rtype = row.get("_type", "").strip()
            if rtype != "data":
                continue
            if conf == "none" or (not only_none and conf == "low"):
                label = row.get("component_label", "").strip()
                if label and label not in seen:
                    seen.add(label)
                    problems.append({
                        "ingredient":    label,
                        "confidence":    conf,
                        "template_id":   row.get("template_id", ""),
                        "current_match": row.get("food_name", row.get("matched_food_name", "")),
                        "notes":         row.get("notes", ""),
                    })

    return problems


# ── Boost file management ─────────────────────────────────────────────────────

def load_existing_boosts(boosts_path: str) -> list[dict]:
    if not os.path.exists(boosts_path):
        return []
    with open(boosts_path, encoding="utf-8") as f:
        return json.load(f)


def save_boosts(boosts_path: str, rules: list[dict]):
    with open(boosts_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def rule_already_exists(existing: list[dict], trigger: str) -> bool:
    """True if a rule with this trigger is already in the list."""
    return any(r.get("trigger", "").lower() == trigger.lower()
               for r in existing)



# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="AI-powered second pass matcher for unresolved ingredients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python ai_matcher.py --debug-csv templates_output_debug.csv
  python ai_matcher.py --debug-csv templates_output_debug.csv --dry-run
  python ai_matcher.py --debug-csv templates_output_debug.csv --only-none
""")
    p.add_argument("--debug-csv",  default="templates_output_debug.csv",
                   help="Debug CSV from recipe_matcher.py (default: templates_output_debug.csv)")

    p.add_argument("--boosts",     default="boosts.json",
                   help="Boost rules file to append to (default: boosts.json)")
    p.add_argument("--dry-run",    action="store_true",
                   help="Print proposed rules without saving")
    p.add_argument("--only-none",  action="store_true",
                   help="Only fix unmatched (pink) rows, skip low confidence (amber)")
    args = p.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # ── Load data ─────────────────────────────────────────────────────────────
    print(f"[→] Loading USDA names from Supabase ...")
    usda_foods = load_usda_names()
    print(f"    {len(usda_foods):,} foods loaded")


    print(f"[→] Reading problem ingredients from {args.debug_csv}")
    problems = load_problem_ingredients(args.debug_csv, args.only_none)
    if not problems:
        print("    No unmatched/low-confidence ingredients found. Nothing to do.")
        return
    print(f"    {len(problems)} unique ingredients to resolve")

    print(f"[→] Loading existing boosts from {args.boosts}")
    existing_boosts = load_existing_boosts(args.boosts)
    print(f"    {len(existing_boosts)} existing rules")

    # ── Resolve each ingredient ───────────────────────────────────────────────
    new_rules: list[dict]    = []
    skipped:   list[str]     = []
    no_fix:    list[str]     = []

    print()
    print(f"{'─'*60}")
    print(f"Resolving {len(problems)} ingredients via Claude...")
    print(f"{'─'*60}")

    for i, prob in enumerate(problems, 1):
        ing  = prob["ingredient"]
        conf = prob["confidence"]
        tid  = prob["template_id"]

        print(f"\n[{i}/{len(problems)}] {ing!r}  ({conf}, from {tid})")

        # Skip if a rule already exists for this trigger
        if rule_already_exists(existing_boosts, ing) or \
           rule_already_exists(new_rules, ing):
            print(f"    → already has a boost rule, skipping")
            skipped.append(ing)
            continue

        # Find candidates
        usda_cands = find_usda_candidates(ing, usda_foods)
        if not usda_cands:
            print(f"    → no USDA candidates found")
            no_fix.append(ing)
            continue

        print(f"    USDA candidates: {len(usda_cands)}")
        if prob["current_match"]:
            print(f"    Current match:   {prob['current_match']!r}  [{prob['notes']}]")

        # Call Claude
        rule = resolve_with_claude(client, ing, usda_cands)
        time.sleep(RETRY_DELAY)

        if rule is None:
            print(f"    → Claude: no fix possible")
            no_fix.append(ing)
            continue

        print(f"    → Rule: {json.dumps(rule)}")
        new_rules.append(rule)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"{'─'*60}")
    print(f"Results:")
    print(f"  New rules generated: {len(new_rules)}")
    print(f"  Already had rules:   {len(skipped)}")
    print(f"  No fix possible:     {len(no_fix)}")
    if no_fix:
        print(f"  Unfixable ingredients:")
        for ing in no_fix:
            print(f"    - {ing}")
    print(f"{'─'*60}")

    if not new_rules:
        print("No new rules to save.")
        return

    all_new_rules = new_rules

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"{'─'*60}")
    print("Final results:")
    print(f"  Matching rules:         {len(new_rules)}")
    print(f"  Already had rules:      {len(skipped)}")
    print(f"  No fix possible:        {len(no_fix)}")
    if no_fix:
        print("  Unfixable ingredients:")
        for ing in no_fix:
            print(f"    - {ing}")
    print(f"{'─'*60}")

    if not all_new_rules:
        print("No new rules to save.")
        return

    if args.dry_run:
        print("\n[dry-run] Proposed rules (not saved):")
        print(json.dumps(all_new_rules, indent=2, ensure_ascii=False))
        return

    # ── Save ─────────────────────────────────────────────────────────────────
    merged = existing_boosts + all_new_rules
    save_boosts(args.boosts, merged)
    print(f"\n[OK] Saved {len(all_new_rules)} new rule(s) to {args.boosts}")
    print(f"     Total rules now: {len(merged)}")
    print()
    print(f"Next step: re-run recipe_matcher.py with --boosts {args.boosts}")


if __name__ == "__main__":
    main()
