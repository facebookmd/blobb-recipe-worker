"""
Compares the two ways a USDA head match can count (HEAD_SCORING in
recipe_matcher.py) on recipe lines whose food someone has already chosen:
the published templates' components, paired in order with their parsed
lines in recipes.csv. Sections a published template copied in from another
(its "Dashi Stock") have no lines of their own and are left out.

About 30% of templates (chosen by id, so the split never moves) are held
out: tune rules on the rest and judge on those. Prints how often each mode
picks the published food, then only the lines whose food changes between
the modes, with kcal per 100 g.

The published foods were picked with the floor mode's matcher and then
reviewed, so where a line's published food is the floor's pick that may be
the review agreeing or only the old matcher's habit: judge the changed
lines by eye, not by the count alone.

Needs SUPABASE_ANON_KEY (USDA project) and APP_SUPABASE_KEY (app project).

Run: .venv/bin/python head_scoring_trial.py [--json out.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import zlib
from collections import defaultdict

import recipe_matcher as matcher
import template_refs as tref

HELD_OUT_SHARE = 0.3


def held_out(template_id: str) -> bool:
    return zlib.crc32(template_id.encode()) % 100 < HELD_OUT_SHARE * 100


def labeled_lines(recipes_csv: str = "recipes.csv") -> list[dict]:
    """Each parsed recipe line with the food its published template chose."""
    components = tref._app_request(
        "meal_template_components?select=template_id,name,food_id,sort_order,"
        "sub_template_name&order=template_id,sort_order&limit=10000")
    published = defaultdict(list)
    for c in components:
        published[(c["template_id"], c["sub_template_name"] or "Main")].append(c)

    rows = list(csv.DictReader(open(recipes_csv, encoding="utf-8")))
    template_of = {}
    for r in rows:
        for name in [r["template_name"], *tref.parse_aka(r["other_names"])]:
            template_of[tref.template_key(name)] = r["template_id"]
    sections = defaultdict(list)
    for r in rows:
        sections[(r["template_id"], r["section"])].append(r)

    lines = []
    for key, section in sections.items():
        # A line naming another template is copied in as its own section; a
        # "to taste" line has no amount. Neither is a published component.
        kept = [r for r in section
                if "to taste" not in r["unit"].lower()
                and template_of.get(tref.template_key(r["ingredient"])) in (None, key[0])]
        chosen = published.get(key, [])
        if len(kept) != len(chosen):
            print(f"[!] {key}: {len(kept)} lines, {len(chosen)} published; skipped")
            continue
        for r, c in zip(kept, chosen):
            lines.append({**r, "truth_fdc": str(c["food_id"]), "truth_name": c["name"],
                          "held_out": held_out(key[0])})
    return lines


def pick(line: dict, boosts: list) -> dict | None:
    """The food the batch pipeline picks for *line*: an alias, else the match."""
    alias = matcher._alias_match(line["ingredient"], line["size_hint"], line["unit"])
    if alias is not None:
        return alias[0]
    is_cooked = line["is_cooked"].strip().lower() in ("true", "1", "yes")
    return matcher.match_ingredient(line["ingredient"], boosts, 0.45, line["category"],
                                    line["unit"], is_cooked=is_cooked)[0]


def run(mode: str, lines: list[dict], boosts: list) -> list[dict | None]:
    matcher.HEAD_SCORING = mode
    matcher._MATCH_CACHE.clear()
    return [pick(line, boosts) for line in lines]


def fdc(food: dict | None) -> str:
    return str(food["fdc_id"]).removeprefix("B_") if food else ""


def describe(food: dict | None) -> str:
    if food is None:
        return "(no match)"
    tag = "[B] " if food.get("source") == "branded" else ""
    return f"{tag}{food['display_name']} ({food.get('energy_kcal') or 0:.0f} kcal)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write every line's picks here")
    args = ap.parse_args()

    boosts = matcher.load_boosts("boosts.json")
    lines = labeled_lines()
    picks = {mode: run(mode, lines, boosts) for mode in ("floor", "tier")}

    for part, wanted in (("dev", False), ("held out", True)):
        idx = [i for i, line in enumerate(lines) if line["held_out"] == wanted]
        agree = {m: sum(fdc(picks[m][i]) == lines[i]["truth_fdc"] for i in idx) for m in picks}
        print(f"{part:9} {len(idx):4} lines   published food picked: "
              f"floor {agree['floor']}, tier {agree['tier']}")

    changed = [i for i in range(len(lines)) if fdc(picks["floor"][i]) != fdc(picks["tier"][i])]
    print(f"\n{len(changed)} lines change food:")
    for i in changed:
        line, floor, tier = lines[i], picks["floor"][i], picks["tier"][i]
        mark = {fdc(floor): "floor", fdc(tier): "tier"}.get(line["truth_fdc"], "neither")
        kcal = ((tier or {}).get("energy_kcal") or 0) - ((floor or {}).get("energy_kcal") or 0)
        print(f"\n{'[held out] ' if line['held_out'] else ''}{line['template_id']}: "
              f"{line['qty']} {line['unit']} {line['ingredient']}   "
              f"(published matches {mark}; tier - floor = {kcal:+.0f} kcal/100 g)")
        print(f"  floor:     {describe(floor)}")
        print(f"  tier:      {describe(tier)}")
        print(f"  published: {line['truth_name']}")

    if args.json:
        json.dump([{**line, "floor": describe(picks["floor"][i]), "floor_fdc": fdc(picks["floor"][i]),
                    "tier": describe(picks["tier"][i]), "tier_fdc": fdc(picks["tier"][i])}
                   for i, line in enumerate(lines)], open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
