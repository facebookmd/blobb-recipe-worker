"""
Compares each template's calories per serving with its outside reference
(calorie_references.json) and lists the ones to look at: more than
MAX_SHARE_OFF and more than MIN_KCAL_OFF away, and new templates with no
reference yet. recipe_matcher.py runs it after writing its output; it only
reports, it never changes a template.

A reference is a recipe page's printed calories per serving, normalised to
our serving (RECIPE_RULES.md, "Calorie reference"). Many blog nutrition
boxes are worked out by a plugin from old USDA data, so a match with one is
not proof; those are kept with status "not_comparable" and a note saying why.

Two kinds are compared, and counted apart: "ok" is a printed figure divided
to our serving, an independent check; "recipe_match" is a real recipe's own
amounts run through our rows, or rescaled to our main-ingredient amount, so
it checks our amounts but not our calorie data.

Run: .venv/bin/python check_template_calories.py [templates_output.csv]
     [--references calorie_references.json] [--json report.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REFERENCES = os.path.join(HERE, "calorie_references.json")

# Flagged when both hold: 13% off (Arianna, 25 Nov 2026; was 20% from the
# 11 Nov audit) and 30 kcal off, so a 27 kcal salad 7 kcal off isn't a flag.
MAX_SHARE_OFF = 0.13
MIN_KCAL_OFF = 30.0

INDEPENDENT = "ok"
RECIPE_MATCH = "recipe_match"
COMPARED = (INDEPENDENT, RECIPE_MATCH)


def template_calories(csv_path: str) -> "OrderedDict[str, dict]":
    """Each template in the matcher's output, in file order: its name and
    calories per serving (the output's cal_tot is already per serving)."""
    out: OrderedDict[str, dict] = OrderedDict()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = (row.get("template_id") or "").strip()
            if not tid:
                continue
            entry = out.setdefault(tid, {"name": row.get("template_name") or tid, "kcal": 0.0})
            try:
                entry["kcal"] += float(row.get("cal_tot") or 0)
            except ValueError:
                pass
    return out


def load_references(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("templates", {})


def check(templates: "OrderedDict[str, dict]", references: dict[str, dict]) -> dict:
    """{"flagged": [...], "missing": [...], "unchecked": [...], "ok": n,
    "recipe_match": n}: flagged are compared templates off by both limits
    (each with its status); ok and recipe_match count the rest by kind;
    missing have no entry in the references; unchecked have one that can't
    be compared (its status)."""
    flagged, missing, unchecked = [], [], []
    within = {INDEPENDENT: 0, RECIPE_MATCH: 0}
    for tid, t in templates.items():
        ours = round(t["kcal"])
        ref = references.get(tid)
        if ref is None:
            missing.append({"id": tid, "name": t["name"], "ours": ours})
            continue
        if ref.get("status") not in COMPARED or not ref.get("kcal"):
            unchecked.append({"id": tid, "name": t["name"], "ours": ours,
                              "status": ref.get("status") or "none"})
            continue
        want = float(ref["kcal"])
        off = ours - want
        if abs(off) > MIN_KCAL_OFF and abs(off) > MAX_SHARE_OFF * want:
            flagged.append({"id": tid, "name": t["name"], "ours": ours, "reference": round(want),
                            "share_off": round(off / want, 3), "status": ref["status"],
                            "url": ref.get("url"),
                            "note": ref.get("note")})
        else:
            within[ref["status"]] += 1
    flagged.sort(key=lambda r: -abs(r["share_off"]))
    return {"flagged": flagged, "missing": missing, "unchecked": unchecked,
            "ok": within[INDEPENDENT], "recipe_match": within[RECIPE_MATCH]}


def report(result: dict, out=sys.stdout) -> None:
    flagged, missing, unchecked = result["flagged"], result["missing"], result["unchecked"]
    print(f"\n[→] Calorie check: {result['ok']} within {MAX_SHARE_OFF:.0%} of a printed reference, "
          f"{result['recipe_match']} of a real recipe's amounts with our rows, "
          f"{len(flagged)} off, {len(missing)} without a reference, "
          f"{len(unchecked)} with a reference that can't be compared.", file=out)
    if flagged:
        print(f"    Off by more than {MAX_SHARE_OFF:.0%} and {MIN_KCAL_OFF:.0f} kcal (look for the cause before importing):", file=out)
        for r in flagged:
            kind = "" if r["status"] == INDEPENDENT else ", recipe's amounts with our rows"
            print(f"      {r['id']}: ours {r['ours']} kcal, reference {r['reference']} "
                  f"({r['share_off']:+.0%}{kind})", file=out)
            if r.get("note"):
                print(f"        known: {r['note']}", file=out)
    if missing:
        print("    No reference yet: add one to calorie_references.json "
              "(RECIPE_RULES.md, 'Calorie reference'):", file=out)
        print("      " + ", ".join(r["id"] for r in missing), file=out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Template calories against outside references.")
    p.add_argument("output", nargs="?", default=os.path.join(HERE, "templates_output.csv"),
                   help="The matcher's CSV output (default: templates_output.csv)")
    p.add_argument("--references", default=DEFAULT_REFERENCES)
    p.add_argument("--json", help="Also write the result here")
    args = p.parse_args(argv)
    if not os.path.exists(args.references):
        print(f"[!] Calorie check skipped: {args.references} not found.")
        return 0
    result = check(template_calories(args.output), load_references(args.references))
    report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
