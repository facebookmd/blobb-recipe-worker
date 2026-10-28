"""
Writes RECIPE_RULES.md's frying-oil table from the app project's fry_types
table (fry_rates.py), the one copy of the rates. Run it after a rate changes:

    APP_SUPABASE_KEY=... .venv/bin/python sync_fry_rates.py

--check exits 1 when the doc differs from the table, without writing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fry_rates

RULES = Path(__file__).resolve().parent / "RECIPE_RULES.md"
START = "<!-- fry_types:start (sync_fry_rates.py writes this table) -->"
END = "<!-- fry_types:end -->"


def _percent(rate: float) -> str:
    return f"{round(rate * 100, 1):g}%"


def table(types: list[dict]) -> str:
    """The Markdown table for [types], lightest first."""
    lines = ["| Method and food | Absorbed oil (% of the raw food's edible weight) |",
             "|---|---|"]
    lines += [f"| {t['rule_label']} | {_percent(t['rate'])} |" for t in types]
    return "\n".join(lines)


def synced(doc: str, types: list[dict]) -> str:
    """[doc] with the table between the markers replaced."""
    start, end = doc.find(START), doc.find(END)
    if start < 0 or end < start:
        raise ValueError(f"{RULES.name}: the fry_types markers are missing.")
    return f"{doc[:start + len(START)]}\n{table(types)}\n{doc[end:]}"


def main(argv: list[str]) -> int:
    doc = RULES.read_text(encoding="utf-8")
    try:
        types = fry_rates.load_fry_types(force=True)
    except fry_rates.FryTypesUnavailable as e:
        print(e, file=sys.stderr)
        return 2
    new = synced(doc, types)
    if "--check" in argv:
        if new != doc:
            print(f"{RULES.name}'s frying table differs from fry_types; run sync_fry_rates.py.")
            return 1
        print(f"{RULES.name}'s frying table matches fry_types.")
        return 0
    if new != doc:
        RULES.write_text(new, encoding="utf-8")
        print(f"Wrote {RULES.name}'s frying table from fry_types.")
    else:
        print(f"{RULES.name}'s frying table already matches fry_types.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
