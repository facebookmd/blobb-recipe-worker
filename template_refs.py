"""
Base templates used inside other recipes.

A recipe line that names a base template, by its name or an AKA ("1.5 cup
dashi stock"), is not looked up as a food. The template's ingredients are
copied into the recipe as their own section, named after the template, and
scaled by the amount: amount ÷ the template's serving size (Dashi Stock:
Servings 4, Serving size 1 cup, so 1.5 cup is 1.5 servings). Copies, not
links: editing a base template later never changes recipes made from it.

Where templates come from:
  * batch runs (recipe_matcher.main): templates earlier in the same run, then
    templates from earlier runs in the output file. Not published templates:
    the import replaces the whole curated set, so they are about to go.
  * the recipe worker (app.py): curated published templates (no
    submitted_by), so a user's own template never takes over a match.

Rows of a referenced template are per one serving of it, as the parser wrote
them (amounts ÷ Servings), so scaling is a multiply.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

ML_PER = {
    "tsp": 4.92892, "tbsp": 14.7868, "cup": 236.588, "fl oz": 29.5735,
    "ml": 1.0, "l": 1000.0, "pint": 473.176, "quart": 946.353,
    "gallon": 3785.41,
}
GRAMS_PER = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237}
SERVING_UNITS = {"serving", "servings"}


class TemplateReferenceError(ValueError):
    """A recipe line names a base template but can't use it; the message
    says why and how to write it."""


@dataclass
class TemplateRef:
    tid: str
    name: str
    aka: list[str] = field(default_factory=list)
    servings: float = 1.0
    serving_qty: float | None = None
    serving_unit: str = ""
    # "run" (this batch), "output" (an earlier batch), "published".
    source: str = "run"
    # Per-serving output rows; for "run" templates, filled once processed.
    rows: list[dict] | None = None
    # The recipe file's Category (published: the template's cuisine).
    category: str = ""


# ── Names ───────────────────────────────────────────────────────────────────

def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def template_key(text: str) -> str:
    """'Ramen Eggs' and 'ramen egg' alike: lower case, letters and digits
    only, each word singular."""
    words = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
    return " ".join(_singular(w) for w in words)


def parse_aka(other_names: str) -> list[str]:
    """The AKA line's names: 'Dashi", "Dashi broth' -> ['Dashi', 'Dashi broth']."""
    text = (other_names or "").strip()
    if not text:
        return []
    return [n.strip().strip('"').strip() for n in text.split('", "') if n.strip().strip('"').strip()]


def build_index(refs: list[TemplateRef]) -> dict[str, TemplateRef]:
    """Name and AKA keys to templates; earlier refs win (pass them in
    precedence order: run, output, published)."""
    index: dict[str, TemplateRef] = {}
    for ref in refs:
        for name in [ref.name, *ref.aka]:
            key = template_key(name)
            if key and key not in index:
                index[key] = ref
    return index


def build_cuisine_index(refs: list[TemplateRef]) -> dict[tuple[str, str], TemplateRef]:
    """(cuisine, name) keys to templates, earlier refs winning as in
    build_index. Two cuisines may each have a "Chicken Stock"; a recipe
    uses its own cuisine's."""
    index: dict[tuple[str, str], TemplateRef] = {}
    for ref in refs:
        cuisine = ref.category.strip().lower()
        if not cuisine:
            continue
        for name in [ref.name, *ref.aka]:
            key = template_key(name)
            if key and (cuisine, key) not in index:
                index[(cuisine, key)] = ref
    return index


def find(
    ingredient: str,
    category: str,
    index: dict[str, TemplateRef],
    cuisine_index: dict[tuple[str, str], TemplateRef],
) -> TemplateRef | None:
    """The template [ingredient] names: the recipe's own cuisine's first,
    then any cuisine's."""
    key = template_key(ingredient)
    if not key:
        return None
    return cuisine_index.get((category.strip().lower(), key)) or index.get(key)


def near_miss(ingredient: str, index: dict[str, TemplateRef]) -> str | None:
    """The template name [ingredient] is probably a typo of ('dashi stok'),
    or None."""
    key = template_key(ingredient)
    if not key or key in index:
        return None
    close = difflib.get_close_matches(key, list(index), n=1, cutoff=0.88)
    return index[close[0]].name if close else None


# ── Amounts ─────────────────────────────────────────────────────────────────

def _row_grams(row: dict) -> float:
    try:
        return float(row.get("unit_grams") or 0) * float(row.get("portion_amt") or 0)
    except (TypeError, ValueError):
        return 0.0


def servings_of(qty: float, unit: str, ref: TemplateRef) -> float:
    """How many servings of [ref] '[qty] [unit]' is."""
    unit = (unit or "").strip().lower()
    serving_unit = (ref.serving_unit or "").strip().lower()
    if unit in SERVING_UNITS:
        return qty
    if not ref.serving_qty or not serving_unit:
        raise TemplateReferenceError(
            f"'{ref.name}' has no Serving size, so '{_amount(qty, unit)} "
            f"{ref.name.lower()}' can't be converted. Add e.g. "
            f"'Serving size: 1 cup' to its block."
        )
    if unit in ML_PER and serving_unit in ML_PER:
        return qty * ML_PER[unit] / (ref.serving_qty * ML_PER[serving_unit])
    if unit in GRAMS_PER:
        per_serving = sum(_row_grams(r) for r in ref.rows or [] if r.get("_type") == "data")
        if per_serving > 0:
            return qty * GRAMS_PER[unit] / per_serving
    if serving_unit not in ML_PER and serving_unit not in GRAMS_PER:
        # A count ("1 slice", "1 whole"): the same noun, or no unit at all
        # ("2 ramen eggs").
        if not unit or _singular(unit) == _singular(serving_unit):
            return qty / ref.serving_qty
    raise TemplateReferenceError(
        f"'{_amount(qty, unit)} {ref.name.lower()}': {ref.name} is measured "
        f"in {_amount(ref.serving_qty, serving_unit)}, so write it in "
        f"{serving_unit or 'servings'}."
    )


def _amount(qty: float, unit: str) -> str:
    text = f"{qty:g}"
    return f"{text} {unit}".strip()


# ── Copying ─────────────────────────────────────────────────────────────────

def expanded_rows(ref: TemplateRef, servings: float, parent: dict) -> list[dict]:
    """[ref]'s rows scaled to [servings], as rows of the [parent] recipe
    (template_id, template_name, category, other_names) in a section named
    after [ref]. Its own sections merge into that one."""
    out = []
    for row in ref.rows or []:
        if row.get("_type") not in ("data", "note"):
            continue
        new = {**row, **parent, "section": ref.name, "sub_template_id": ref.tid}
        if row.get("_type") == "data":
            try:
                amt = float(row.get("portion_amt") or 0) * servings
            except (TypeError, ValueError):
                amt = 0.0
            new["portion_amt"] = amt
            cal = row.get("calories_kcal")
            new["cal_tot"] = round(cal * amt, 1) if isinstance(cal, (int, float)) else ""
            note = str(row.get("notes") or "")
            new["notes"] = f"from {ref.name} x{servings:.4g}; {note}".strip("; ")
        out.append(new)
    return out


def merge_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """[new_rows] not already in [existing]; the ones that are (same section,
    food and portion, or the same note) are added into those rows instead."""
    appended = []
    for row in new_rows:
        if row.get("_type") == "note":
            same = next((r for r in existing + appended if r.get("_type") == "note"
                         and r.get("template_id") == row.get("template_id")
                         and r.get("section") == row.get("section")
                         and r.get("component_label") == row.get("component_label")), None)
            if same is None:
                appended.append(row)
            continue
        same = next((r for r in existing + appended if r.get("_type") == "data"
                     and r.get("food_id")
                     and r.get("template_id") == row.get("template_id")
                     and r.get("section") == row.get("section")
                     and r.get("food_id") == row.get("food_id")
                     and r.get("portion_id") == row.get("portion_id")), None)
        if same is None:
            appended.append(row)
            continue
        same["portion_amt"] = float(same.get("portion_amt") or 0) + float(row.get("portion_amt") or 0)
        cal = same.get("calories_kcal")
        if isinstance(cal, (int, float)):
            same["cal_tot"] = round(cal * same["portion_amt"], 1)
    return appended


# ── Published templates (recipe worker) ─────────────────────────────────────

APP_SUPABASE_URL = os.environ.get(
    "APP_SUPABASE_URL", "https://qaekljlqmqojdtuqofwb.supabase.co").rstrip("/")
_CACHE_SECONDS = 600
_cache: tuple[float, list[TemplateRef]] | None = None
_cache_lock = threading.Lock()


def _app_key() -> str:
    return os.environ.get("APP_SUPABASE_KEY", "").strip()


def load_published_templates(*, force: bool = False) -> list[TemplateRef]:
    """Curated published templates (no submitted_by) that have a serving
    size, with their components as per-serving rows. Cached for 10 minutes.
    Empty, with a warning, when APP_SUPABASE_KEY is unset or the request
    fails: lines then match foods as before."""
    global _cache
    with _cache_lock:
        if not force and _cache and time.time() - _cache[0] < _CACHE_SECONDS:
            return _cache[1]
        refs: list[TemplateRef] = []
        if not _app_key():
            print("[!] APP_SUPABASE_KEY unset: recipes can't use published templates.",
                  file=sys.stderr)
        else:
            try:
                refs = _fetch_published_templates()
            except RuntimeError as e:
                print(f"[!] Published templates failed to load: {e}", file=sys.stderr)
                if _cache:
                    return _cache[1]
        _cache = (time.time(), refs)
        return refs


def _app_request(path: str) -> list[dict]:
    import json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    key = _app_key()
    req = Request(f"{APP_SUPABASE_URL}/rest/v1/{path}", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if e.fp else ""
        raise RuntimeError(f"({e.code}) {detail or e.reason}") from e
    except URLError as e:
        raise RuntimeError(str(e.reason)) from e
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected response {type(data)!r}")
    return data


def _fetch_published_templates() -> list[TemplateRef]:
    import supabase_food_source as food_source

    templates = _app_request(
        "meal_templates?select=id,name,aka,cuisine,serving_qty,serving_unit"
        "&is_published=eq.true&submitted_by=is.null&serving_qty=not.is.null")
    if not templates:
        return []
    ids = ",".join(quote(f'"{t["id"]}"', safe="") for t in templates)
    components = _app_request(
        "meal_template_components?select=template_id,name,food_id,default_qty,"
        "unit_label,unit_grams,sub_template_name,sort_order"
        f"&template_id=in.({ids})&order=sort_order")
    fdc_ids = sorted({int(c["food_id"]) for c in components if c.get("food_id") is not None})
    foods: dict[int, dict] = {}
    for start in range(0, len(fdc_ids), 100):
        chunk = ",".join(str(i) for i in fdc_ids[start:start + 100])
        rows = food_source._request_json(
            f"{food_source._supabase_url()}/rest/v1/foods"
            f"?select=fdc_id,source_set,display_name,calories_100g&fdc_id=in.({chunk})")
        for row in rows:
            foods.setdefault(int(row["fdc_id"]), row)

    by_template: dict[str, list[dict]] = {}
    unusable: set[str] = set()
    for c in components:
        food = foods.get(int(c["food_id"])) if c.get("food_id") is not None else None
        grams = c.get("unit_grams")
        if food is None or not c.get("unit_label") or not grams:
            unusable.add(c["template_id"])
            continue
        branded = str(food.get("source_set", "")).lower() == "branded"
        fdc = int(food["fdc_id"])
        grams = float(grams)
        cal = round(grams / 100.0 * float(food.get("calories_100g") or 0), 1)
        amt = float(c.get("default_qty") or 0)
        by_template.setdefault(c["template_id"], []).append({
            "_type": "data", "_confidence": "high",
            "_source": "branded" if branded else "usda",
            "component_label": c.get("name") or food.get("display_name", ""),
            "matched_food_name": food.get("display_name", ""),
            "food_id": f"B_{fdc}" if branded else str(fdc),
            "portion_id": f"tpl-{c['template_id']}-{c.get('sort_order')}",
            "portion_amt": amt,
            "portion_description": f"{c['unit_label']} ({grams:.0f} g)",
            "unit_label": c["unit_label"], "unit_grams": grams,
            "calories_kcal": cal, "cal_tot": round(cal * amt, 1),
            "section": c.get("sub_template_name") or "Main",
            "notes": "",
        })

    refs = []
    for t in templates:
        if t["id"] in unusable or t["id"] not in by_template:
            continue
        refs.append(TemplateRef(
            tid=t["id"], name=t["name"], aka=list(t.get("aka") or []),
            serving_qty=float(t["serving_qty"]), serving_unit=t.get("serving_unit") or "",
            source="published", rows=by_template[t["id"]],
            category=t.get("cuisine") or "",
        ))
    return refs
