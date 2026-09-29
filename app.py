"""
HTTP wrapper around the recipe pipeline, deployed as the Cloud Run service
`blobb-recipe-worker`. The Flutter app's "Convert recipe" calls it.

    GET  /health        -> {"status": "ok"}
    POST /parse-recipe  {"text": "..."} -> {"template": {...}, ...}
                        needs `Authorization: Bearer <app session token>`;
                        see auth.py for who may call it and how often.

The template JSON matches `MealTemplate.fromJson` in the app
(`lib/data/meal_template.dart`); `foodId` is the FDC ID.

Matching runs through `recipe_matcher.build_output_rows`, the same function
that produces templates_output.xlsx, so a recipe converted in the app gets the
same foods, portions and amounts as the spreadsheet. Needs SUPABASE_ANON_KEY.
"""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import AuthError, Caller, RateLimiter, TokenVerifier

import parse_recipe as recipe_parser
import recipe_matcher as matcher

HERE = Path(__file__).resolve().parent
BOOST_RULES = matcher.load_boosts(str(HERE / "boosts.json"))


class ParseRequest(BaseModel):
    text: str = Field(..., min_length=1)
    threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    category: str = ""


class ParseResponse(BaseModel):
    template: dict[str, Any]
    matched_count: int
    unmatched_count: int
    # Ingredient names left out of the template, so the app can say which.
    unmatched: list[str] = Field(default_factory=list)


app = FastAPI(title="Blobb Recipe Parser", version="2.1.0")

# Each ingredient runs food searches, so the text and the ingredient count
# are capped; a real recipe is far below both.
MAX_TEXT_CHARS = 10_000
MAX_INGREDIENTS = 60

verifier = TokenVerifier()
# Per user: 10 conversions an hour, 30 a day.
user_limits = RateLimiter([(10, 3600.0), (30, 86400.0)])


def require_caller(authorization: Optional[str] = Header(default=None)) -> Caller:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in to convert recipes.")
    try:
        caller = verifier.verify(token.strip())
    except AuthError:
        raise HTTPException(status_code=401, detail="Sign in to convert recipes.")
    if not user_limits.allow(caller.user_id):
        raise HTTPException(
            status_code=429,
            detail="You've converted a lot of recipes. Try again in an hour.",
        )
    return caller


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _fdc_int(food_id: Any) -> int | None:
    """USDA ids are plain numbers; branded ones carry a "B_" prefix."""
    text = str(food_id or "").strip()
    if text.startswith("B_"):
        text = text[2:]
    try:
        return int(text)
    except ValueError:
        return None


def _find_food(food_id: str) -> dict | None:
    """The food dict the matcher picked, from its per-ingredient search cache."""
    for index in matcher._INGREDIENT_INDEX_CACHE.values():
        food = index.get(food_id, fetch=False)
        if food is not None:
            return food
    return None


_GRAMS_RE = re.compile(r"\((\d+(?:\.\d+)?) g\)$")


def _chosen_unit(row: dict) -> dict[str, Any]:
    """The portion the matcher chose, as the row describes it."""
    desc = str(row.get("portion_description") or "").strip()
    calories = _number(row.get("calories_kcal"))
    if desc == "100g":
        return {"label": "100 g", "caloriesPerUnit": calories, "gramsPerUnit": 100.0}
    match = _GRAMS_RE.search(desc)
    grams = float(match.group(1)) if match else None
    label = _GRAMS_RE.sub("", desc).strip() or "serving"
    return {"label": label, "caloriesPerUnit": calories, "gramsPerUnit": grams}


def _units_for(row: dict) -> tuple[list[dict[str, Any]], int]:
    """Every portion of the matched food, with the chosen one as the default.

    Calories for the other portions are scaled from the chosen one, so all of
    a component's units agree on kcal per gram.
    """
    chosen = _chosen_unit(row)
    food = _find_food(str(row.get("food_id") or ""))
    grams = chosen["gramsPerUnit"]
    if food is None or not grams:
        return [chosen], 0

    kcal_per_gram = chosen["caloriesPerUnit"] / grams
    units: list[dict[str, Any]] = []
    default_index = None
    for portion in food.get("portions") or []:
        weight = _number(portion.get("gram_weight"))
        if weight <= 0:
            continue
        label = str(portion.get("label") or "").strip() or "serving"
        if label.lower() in ("100g", "100 g"):
            label = "100 g"
        if default_index is None and portion.get("portion_id") == row.get("portion_id"):
            default_index = len(units)
        units.append({
            "label": label,
            "caloriesPerUnit": round(kcal_per_gram * weight, 2),
            "gramsPerUnit": weight,
        })

    if default_index is None:
        units.insert(0, chosen)
        default_index = 0
    return units, default_index


def _unmatched_name(row: dict) -> str:
    return str(row.get("component_label") or row.get("matched_food_name") or "").strip()


def _match_recipe(text: str, threshold: float, category: str) -> ParseResponse:
    meta, ingredients = recipe_parser.parse_single_block(
        text.replace("\r\n", "\n").split("\n"),
        name_hint="recipe",
        category_override=category,
    )
    if not ingredients:
        raise HTTPException(status_code=422, detail="No ingredients found in that text.")
    if len(ingredients) > MAX_INGREDIENTS:
        raise HTTPException(
            status_code=413,
            detail=f"That recipe has more than {MAX_INGREDIENTS} ingredients.",
        )

    with tempfile.TemporaryDirectory() as tmp:
        recipes_csv = os.path.join(tmp, "recipes.csv")
        recipe_parser.write_recipes_csv([(meta, ingredients)], recipes_csv, append=False)
        rows = matcher.build_output_rows(recipes_csv, BOOST_RULES, threshold)

    sections: dict[str, list[dict[str, Any]]] = {}
    matched_count = 0
    unmatched: list[str] = []
    for row in rows:
        # "note" rows are "to taste" ingredients, left out on purpose.
        if row.get("_type") != "data":
            continue
        if row.get("_source") not in ("usda", "branded") or not row.get("food_id"):
            unmatched.append(_unmatched_name(row))
            continue

        units, default_index = _units_for(row)
        component = {
            "name": str(row.get("component_label") or row.get("matched_food_name") or "Ingredient"),
            "foodId": _fdc_int(row.get("food_id")),
            "defaultQty": round(_number(row.get("portion_amt"), 1.0), 3),
            "defaultUnitIndex": default_index,
            "units": units,
        }
        sections.setdefault(row.get("section") or "Main", []).append(component)
        matched_count += 1

    if not sections:
        raise HTTPException(status_code=422, detail="No ingredients could be matched.")

    sub_templates = [{"name": name, "components": comps} for name, comps in sections.items()]
    default_calories = sum(
        c["units"][c["defaultUnitIndex"]]["caloriesPerUnit"] * c["defaultQty"]
        for sub in sub_templates
        for c in sub["components"]
    )
    title = str(meta.get("template_name") or "").strip() or "New Recipe"
    return ParseResponse(
        template={
            "id": f"recipe_{recipe_parser.slugify(title)}_{uuid.uuid4().hex[:8]}",
            "name": title,
            "defaultCalories": round(default_calories),
            "subTemplates": sub_templates,
        },
        matched_count=matched_count,
        unmatched_count=len(unmatched),
        unmatched=[name for name in unmatched if name],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/parse-recipe", response_model=ParseResponse)
def parse_recipe(
    request: ParseRequest,
    caller: Caller = Depends(require_caller),
) -> ParseResponse:
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Recipe text is empty.")
    if len(request.text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="That recipe is too long.")
    return _match_recipe(request.text, request.threshold, request.category)
