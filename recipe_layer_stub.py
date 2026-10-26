"""Test helper: the recipe layer (recipe_matcher._match_ingredient_once) on
a given set of foods, with layer 1's search and the portion lookup stubbed.

    best("garlic", [fndds, legacy], "clove") is legacy

The foods are built food dicts (as the tests' usda() helpers make them);
layer 1 ranks them as it ranks live rows, and the recipe layer picks one.
Returns the very dict passed in, or None.
"""

from __future__ import annotations

from unittest import mock

import food_name_search as layer1
import recipe_matcher as matcher


def _row(food: dict) -> dict:
    fdc = str(food["fdc_id"])
    branded = food.get("source") == "branded"
    data_type = food.get("data_type") or ("Branded" if branded else "SR Legacy")
    row = {"id": int(fdc.removeprefix("B_")), "fdc_id": int(fdc.removeprefix("B_")),
           "description": food.get("raw_description") or food.get("item_name") or food["display_name"],
           "display_name": food["display_name"], "category": food.get("category", ""),
           "source_set": "branded" if branded else data_type.lower().replace(" ", "_"),
           "data_type": data_type, "calories_100g": food.get("energy_kcal")}
    for key in ("serving_size", "serving_size_unit", "household_serving_full_text"):
        if key in food:
            row[key] = food[key]
    return row


def best(search: str, foods: list[dict], unit: str = "", is_cooked: bool = False,
         rules=()) -> dict | None:
    rows = [_row(f) for f in foods]
    by_id = {r["id"]: f for r, f in zip(rows, foods)}

    def search_rows(text, limit=60):
        split = layer1.split_portion_words(text)
        query = layer1.Query.parse(split.food)
        words = {layer1.canonical(t) for t in query.tokens}
        found = [r for r in rows
                 if words & {layer1.canonical(t) for t in layer1.tokens(
                     f"{r['description']} {r['display_name']}")}]
        return layer1.rank_rows(query, found, None, split.product_cuts), split

    def portions(ids):
        return {i: [{"label": p["label"], "grams": p["gram_weight"], "sequence_number": n}
                    for n, p in enumerate(by_id[i].get("portions", []), 1)
                    if p.get("portion_idx", 1) != 0]
                for i in ids}

    with mock.patch.object(layer1, "search", search_rows), \
            mock.patch.object(matcher, "load_portions_for_food_ids", portions), \
            mock.patch.object(matcher, "_respelled", lambda ingredient, *a, **k: ingredient), \
            mock.patch.object(matcher, "_MATCH_CACHE", {}), \
            mock.patch.object(matcher, "_search_usda_for_ingredient", lambda q: matcher.USDAIndex()):
        food = matcher.match_ingredient(search, list(rules), 0.45, "", unit, is_cooked)[0]
    if food is None:
        return None
    return by_id.get(int(str(food["fdc_id"]).removeprefix("B_")))
