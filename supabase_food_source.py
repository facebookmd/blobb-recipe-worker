#!/usr/bin/env python3
"""
Helpers for reading the Blobb Supabase food tables.

The template matcher previously loaded USDA food data from local CSV / JSON
exports. This module pulls the same data from the Supabase `foods` and
`food_portions` tables instead, then caches the downloaded rows on disk so the
matching scripts can still start quickly on later runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


DEFAULT_SUPABASE_URL = "https://npjuylxjgaiualfihxpt.supabase.co"
DEFAULT_PAGE_SIZE = 200

_MEMORY_CACHE: dict[tuple[str, str, str, str], list[dict]] = {}


def is_configured() -> bool:
    return bool(_supabase_key())


def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")


def _supabase_key() -> str:
    return (
        os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()


def _cache_dir() -> Path:
    # Prefer a writable temp location; fall back to the script's own folder.
    import tempfile
    return Path(tempfile.gettempdir()) / "blobb_supabase_cache"


def _cache_path(table: str, select: str, order: str, filter_key: str) -> Path:
    cache_key = json.dumps(
        {
            "url": _supabase_url(),
            "table": table,
            "select": select,
            "order": order,
            "filter": filter_key,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:20]
    return _cache_dir() / f"{table}_{digest}.pkl"


def _request_json(path: str) -> list[dict]:
    key = _supabase_key()
    if not key:
        raise RuntimeError(
            "Supabase credentials are missing. Set SUPABASE_ANON_KEY "
            "(and optionally SUPABASE_URL) to use the remote food tables."
        )

    req = Request(
        path,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=120) as resp:
            payload = resp.read().decode("utf-8")
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if e.fp else ""
        raise RuntimeError(
            f"Supabase request failed ({e.code}) for {path}: {detail or e.reason}"
        ) from e
    except URLError as e:
        raise RuntimeError(f"Supabase request failed for {path}: {e.reason}") from e

    data = json.loads(payload)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Supabase response for {path}: {type(data)!r}")
    return data


def _fetch_table_rows(
    table: str,
    select: str,
    *,
    order: str,
    filters: dict[str, str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    force_refresh: bool = False,
) -> list[dict]:
    filters = filters or {}
    filter_key = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    cache_key = (table, select, order, filter_key)

    cached = _MEMORY_CACHE.get(cache_key)
    if cached is not None and not force_refresh:
        return cached

    cache_path = _cache_path(table, select, order, filter_key)
    if cache_path.exists() and not force_refresh:
        with cache_path.open("rb") as f:
            rows = pickle.load(f)
        _MEMORY_CACHE[cache_key] = rows
        return rows

    rows: list[dict] = []
    base_url = _supabase_url()
    last_id: int | None = None

    while True:
        params: list[tuple[str, str]] = [
            ("select", select),
            ("order", order),
            ("limit", str(page_size)),
        ]
        if last_id is not None:
            params.append(("id", f"gt.{last_id}"))
        for key, value in filters.items():
            params.append((key, value))

        url = f"{base_url}/rest/v1/{quote(table)}?{urlencode(params)}"
        page = _request_json(url)
        rows.extend(page)
        if len(page) < page_size:
            break
        last_id = page[-1]["id"]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as f:
        pickle.dump(rows, f, protocol=pickle.HIGHEST_PROTOCOL)

    _MEMORY_CACHE[cache_key] = rows
    return rows


def load_food_rows(
    *,
    source_set: str | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """
    Load rows from public.foods.

    source_set can be:
      - None        → all food rows
      - "branded"   → only branded foods
      - "non-branded" / "usda" → everything except branded foods
    """

    filters: dict[str, str] = {}
    if source_set in {"branded"}:
        filters["source_set"] = "eq.branded"
    elif source_set in {"non-branded", "usda"}:
        filters["source_set"] = "neq.branded"

    return _fetch_table_rows(
        "foods",
        (
            "id, source_set, fdc_id, data_type, food_class, description, "
            "display_name, category, brand_owner, gtin_upc, scientific_name, "
            "ingredients, serving_size, serving_size_unit, "
            "household_serving_full_text, market_country, publication_date, "
            "modified_date, available_date, is_historical_reference, "
            "calories_100g, protein_100g, fat_100g, carbs_100g, fiber_100g"
        ),
        order="id.asc",
        filters=filters,
        force_refresh=force_refresh,
    )


def load_portion_rows(*, force_refresh: bool = False) -> list[dict]:
    return _fetch_table_rows(
        "food_portions",
        (
            "id, food_id, portion_id, label, description, value, grams, "
            "calories, measure_unit_id, measure_unit_name, "
            "measure_unit_abbreviation, modifier, sequence_number, amount, raw_jsonb"
        ),
        order="food_id.asc,id.asc",
        force_refresh=force_refresh,
    )


def group_portions_by_food_id(portion_rows: Iterable[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in portion_rows:
        food_id = row.get("food_id")
        if food_id is None:
            continue
        try:
            food_id_int = int(food_id)
        except (TypeError, ValueError):
            continue
        grouped.setdefault(food_id_int, []).append(dict(row))

    for rows in grouped.values():
        rows.sort(
            key=lambda r: (
                r.get("sequence_number") is None,
                r.get("sequence_number") if r.get("sequence_number") is not None else 0,
                r.get("id") if r.get("id") is not None else 0,
            )
        )
    return grouped


# ── Per-ingredient search (matches app's FoodDatabase.search pattern) ─────────

_FOOD_SEARCH_SELECT = (
    "id, fdc_id, source_set, data_type, description, display_name, "
    "category, brand_owner, gtin_upc, scientific_name, ingredients, "
    "serving_size, serving_size_unit, household_serving_full_text, "
    "is_historical_reference, calories_100g, protein_100g, fat_100g, "
    "carbs_100g, fiber_100g"
)

_PORTION_SELECT = (
    "id, food_id, portion_id, label, description, value, grams, "
    "calories, measure_unit_id, measure_unit_name, "
    "measure_unit_abbreviation, modifier, sequence_number, amount, raw_jsonb"
)

_LIKE_SPECIAL = str.maketrans({"%": r"\%", "_": r"\_"})


def _escape_like(text: str) -> str:
    return text.translate(_LIKE_SPECIAL)


def _build_fts_query(query: str) -> str:
    """Build a prefix tsquery string: 'mirin rice' → 'mirin:* & rice:*'."""
    import re
    tokens = re.findall(r'[a-zA-Z0-9]+', query.lower())
    if not tokens:
        return ""
    return " & ".join(f"{t}:*" for t in tokens)


def search_foods(
    query: str,
    *,
    source_set: str | None = None,
    limit: int = 160,
) -> list[dict]:
    """
    Search the foods table per-ingredient using FTS + ilike fallback.
    Matches the app's FoodDatabase.search() pattern.

    source_set: None=all, "usda"=non-branded, "branded"=branded only.
    Returns raw food rows (not built into food dicts yet).
    """
    if not is_configured():
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_ANON_KEY "
            "(and optionally SUPABASE_URL) environment variables."
        )

    q = query.strip()
    if not q:
        return []

    base_url = _supabase_url()
    rows_by_id: dict[int, dict] = {}

    # Build source_set filter param
    source_filter = ""
    if source_set in {"branded"}:
        source_filter = "&source_set=eq.branded"
    elif source_set in {"non-branded", "usda"}:
        source_filter = "&source_set=neq.branded"

    # Strategy 1: Full-text search via search_vector
    fts = _build_fts_query(q)
    if fts:
        fts_encoded = quote(fts)
        url = (
            f"{base_url}/rest/v1/foods"
            f"?select={quote(_FOOD_SEARCH_SELECT)}"
            f"&search_vector=fts(english).{fts_encoded}"
            f"&limit={limit}"
            f"{source_filter}"
        )
        try:
            for row in _request_json(url):
                rid = row.get("id")
                if rid is not None:
                    rows_by_id[int(rid)] = row
        except RuntimeError:
            pass  # FTS column may not exist; fall through to ilike

    # Strategy 2: ilike fallback (if FTS returned few results)
    if len(rows_by_id) < limit:
        pattern = f"%{_escape_like(q)}%"
        ilike_filters = ",".join([
            f"description.ilike.{pattern}",
            f"display_name.ilike.{pattern}",
            f"category.ilike.{pattern}",
            f"brand_owner.ilike.{pattern}",
            f"ingredients.ilike.{pattern}",
        ])
        url = (
            f"{base_url}/rest/v1/foods"
            f"?select={quote(_FOOD_SEARCH_SELECT)}"
            f"&or=({quote(ilike_filters)})"
            f"&limit={limit}"
            f"{source_filter}"
        )
        try:
            for row in _request_json(url):
                rid = row.get("id")
                if rid is not None:
                    rows_by_id.setdefault(int(rid), row)
        except RuntimeError:
            pass

    return list(rows_by_id.values())


def fetch_food_by_fdc_id(fdc_id: int, *, branded: bool = False) -> dict | None:
    """
    One food row by FDC ID, for the matcher's direct lookups (pinned boosts,
    egg/salmon/tofu shortcuts) when the pinned food isn't among an
    ingredient's search results. Returns the raw row, or None.
    """
    if not is_configured():
        return None
    source_filter = "&source_set=eq.branded" if branded else "&source_set=neq.branded"
    url = (
        f"{_supabase_url()}/rest/v1/foods"
        f"?select={quote(_FOOD_SEARCH_SELECT)}"
        f"&fdc_id=eq.{int(fdc_id)}"
        f"{source_filter}"
        f"&limit=1"
    )
    try:
        rows = _request_json(url)
    except RuntimeError:
        return None
    return rows[0] if rows else None


def load_portions_for_food_ids(food_ids: list[int]) -> dict[int, list[dict]]:
    """
    Load portions only for specific food IDs.
    Returns grouped dict like group_portions_by_food_id().
    """
    if not food_ids or not is_configured():
        return {}

    base_url = _supabase_url()
    all_portions: list[dict] = []

    # Supabase supports in() filter — batch in chunks of 50
    chunk_size = 50
    for i in range(0, len(food_ids), chunk_size):
        chunk = food_ids[i:i + chunk_size]
        id_list = ",".join(str(fid) for fid in chunk)
        url = (
            f"{base_url}/rest/v1/food_portions"
            f"?select={quote(_PORTION_SELECT)}"
            f"&food_id=in.({id_list})"
            f"&order=food_id.asc,id.asc"
            f"&limit=1000"
        )
        try:
            all_portions.extend(_request_json(url))
        except RuntimeError:
            pass

    return group_portions_by_food_id(all_portions)

