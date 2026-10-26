"""
Runs every recipe line in recipes/*.txt through the matcher twice, with its
own name search and with the shared one (BLOBB_NAME_SEARCH, see
recipe_matcher.NAME_SEARCH), and prints only the lines whose food changes,
with calories per 100 g and per serving each way.

Each run is its own process, since the setting is read at import.

Needs SUPABASE_ANON_KEY (USDA project); APP_SUPABASE_KEY too, for lines
that use published templates.

Run: .venv/bin/python compare_name_search.py [--json out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def run(mode: str, out: str) -> None:
    """One mode's output rows, as {template_id, section, line, food, ...}."""
    os.environ["BLOBB_NAME_SEARCH"] = mode
    sys.path.insert(0, HERE)
    import parse_recipe
    import recipe_matcher as matcher

    recipes = []
    for path in sorted(glob.glob(os.path.join(HERE, "recipes", "*.txt"))):
        recipes += parse_recipe.parse_file(path)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "recipes.csv")
        parse_recipe.write_recipes_csv(recipes, csv_path, append=False)
        rows = matcher.build_output_rows(
            csv_path, matcher.load_boosts(os.path.join(HERE, "boosts.json")), 0.45,
            strict_templates=False)
    seen = defaultdict(int)
    lines = []
    for r in rows:
        if r.get("_type") != "data":
            continue
        key = (r["template_id"], r.get("section", ""), r["component_label"])
        seen[key] += 1
        try:
            grams = float(r.get("unit_grams") or 0)
            per100 = float(r.get("calories_kcal") or 0) / grams * 100 if grams else None
        except ValueError:
            per100 = None
        lines.append({"template_id": key[0], "section": key[1], "line": key[2], "n": seen[key],
                      "category": r.get("category", ""), "food": r.get("matched_food_name", ""),
                      "food_id": str(r.get("food_id", "")), "portion": r.get("portion_description", ""),
                      "kcal_100g": per100, "cal_tot": r.get("cal_tot")})
    json.dump(lines, open(out, "w"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(a_path: str, b_path: str) -> list[dict]:
    a = {(x["template_id"], x["section"], x["line"], x["n"]): x for x in json.load(open(a_path))}
    b = {(x["template_id"], x["section"], x["line"], x["n"]): x for x in json.load(open(b_path))}
    changed = []
    for k in a:
        if k in b and a[k]["food_id"] != b[k]["food_id"]:
            ca, cb = _num(a[k]["cal_tot"]), _num(b[k]["cal_tot"])
            changed.append({"key": k, "category": a[k]["category"], "matcher": a[k], "shared": b[k],
                            "d_serving": None if ca is None or cb is None else cb - ca})
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs=2, metavar=("MODE", "OUT"), help=argparse.SUPPRESS)
    ap.add_argument("--json", help="write the changed lines here")
    args = ap.parse_args()
    if args.run:
        run(*args.run)
        return

    with tempfile.TemporaryDirectory() as tmp:
        outs = {}
        for mode in ("matcher", "shared"):
            outs[mode] = os.path.join(tmp, f"{mode}.json")
            subprocess.run([sys.executable, __file__, "--run", mode, outs[mode]], check=True,
                           stderr=subprocess.DEVNULL)
        total = len(json.load(open(outs["matcher"])))
        changed = compare(outs["matcher"], outs["shared"])

    print(f"{len(changed)} of {total} recipe lines change food\n")
    for c in sorted(changed, key=lambda c: -abs(c["d_serving"] or 0)):
        m, s = c["matcher"], c["shared"]

        def kcal(x):
            return f"{x['kcal_100g']:.0f}" if x["kcal_100g"] is not None else "?"
        d = f"{c['d_serving']:+.0f}" if c["d_serving"] is not None else "?"
        print(f"[{c['category']}] {c['key'][0]}: {c['key'][2]}   (per serving {d} kcal)")
        print(f"  matcher: {m['food']} ({kcal(m)} kcal/100 g)")
        print(f"  shared:  {s['food']} ({kcal(s)} kcal/100 g)")
    if args.json:
        json.dump(changed, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
