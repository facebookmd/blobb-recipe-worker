"""
How much frying oil a fried food keeps, by how it was coated or cut: the
app project's fry_types table (blobbapp migration 20261028120000), the one
copy of these rates. The matcher reads them to turn "3 cups oil for frying"
into the absorbed share; app.py sends them to the editor with each
conversion; sync_fry_rates.py writes RECIPE_RULES.md's table from them.
Sources for every rate: ABSORPTION_SOURCES.md.
"""

from __future__ import annotations

import threading
import time

import template_refs

_CACHE_SECONDS = 600
_cache: tuple[float, list[dict]] | None = None
_cache_lock = threading.Lock()

_COLUMNS = "key,label,rule_label,rate,sort_order,sources_summary"


class FryTypesUnavailable(RuntimeError):
    """The fry_types table couldn't be read, so frying oil can't be counted."""


def load_fry_types(*, force: bool = False) -> list[dict]:
    """The fry types, lightest first: key, label, rule_label, rate (a
    float), sort_order, sources_summary. Cached for 10 minutes; a failed
    read keeps the last good copy, and with none raises FryTypesUnavailable
    rather than guessing a rate."""
    global _cache
    with _cache_lock:
        if not force and _cache and time.time() - _cache[0] < _CACHE_SECONDS:
            return _cache[1]
        if not template_refs._app_key():
            if _cache:
                return _cache[1]
            raise FryTypesUnavailable("APP_SUPABASE_KEY unset: frying rates can't be read.")
        try:
            rows = template_refs._app_request(f"fry_types?select={_COLUMNS}&order=sort_order")
        except RuntimeError as e:
            if _cache:
                return _cache[1]
            raise FryTypesUnavailable(f"Frying rates failed to load: {e}") from e
        if not rows:
            raise FryTypesUnavailable("The fry_types table is empty.")
        types = [{**r, "rate": float(r["rate"])} for r in rows]
        _cache = (time.time(), types)
        return types


def rates() -> dict[str, float]:
    """{key: share of the raw edible weight kept as oil}."""
    return {t["key"]: t["rate"] for t in load_fry_types()}


def set_for_tests(types: list[dict] | None) -> None:
    """Use [types] instead of the table (None clears it)."""
    global _cache
    with _cache_lock:
        _cache = (float("inf"), types) if types is not None else None
