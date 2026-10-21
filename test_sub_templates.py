"""Base templates used by name inside other recipes (template_refs.py).

"1.5 cup dashi stock" copies Dashi Stock's ingredients into the recipe as a
"Dashi Stock" section, scaled by amount ÷ serving size (1 cup). Food matching
is stubbed, so these run offline.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher
import template_refs as tref

# Live values (Supabase, 11 Oct 2026).
WATER = matcher._build_supabase_usda_food(
    {"id": 10, "fdc_id": 173647, "source_set": "sr_legacy",
     "description": "Water, tap, drinking", "display_name": "Tap water, drinking",
     "calories_100g": 0},
    0, {10: [{"label": "cup", "grams": 237.0, "sequence_number": 1}]})
DASHI_POWDER = matcher._build_supabase_branded_food(
    {"id": 263996, "fdc_id": 2381716, "source_set": "branded",
     "description": "TRADITIONAL UMAMI DASHI SOUP BASE & SEASONING",
     "display_name": "TRADITIONAL UMAMI DASHI SOUP BASE & SEASONING",
     "calories_100g": 312},
    0, {})
MISO = matcher._build_supabase_usda_food(
    {"id": 11, "fdc_id": 172442, "source_set": "sr_legacy",
     "description": "Miso", "display_name": "Miso", "calories_100g": 198},
    0, {11: [{"label": "tbsp", "grams": 17.0, "sequence_number": 1}]})
PORK = matcher._build_supabase_usda_food(
    {"id": 12, "fdc_id": 167812, "source_set": "sr_legacy",
     "description": "Pork belly, raw", "display_name": "Pork belly, raw",
     "calories_100g": 518},
    0, {12: [{"label": "slice", "grams": 30.0, "sequence_number": 1}]})

FOODS = {"water": WATER, "dashi powder": DASHI_POWDER, "white miso": MISO,
         "pork belly": PORK}
POWDER_TSP = [{"trigger": "dashi powder", "portion_gram_weight": 4.0,
               "portion_label": "1 tsp", "portion_unit": "tsp"}]

DASHI_STOCK = """Dashi Stock
AKA: Dashi", "Dashi broth
Servings: 4
Serving size: 1 cup
4 cup water
4 tsp dashi powder"""


@pytest.fixture
def foods(monkeypatch):
    def fake(ingredient, *a, **k):
        food = FOODS.get(ingredient.lower())
        return (food, 1.0, "high", None) if food else (None, 0.0, "none", None)
    monkeypatch.setattr(matcher, "match_ingredient", fake)
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)


def run(tmp_path, *blocks, published=None, strict=True):
    recipes = [parse_recipe.parse_single_block(b.split("\n"), name_hint="recipe")
               for b in blocks]
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv(recipes, str(csv), append=False)
    return matcher.build_output_rows(str(csv), POWDER_TSP, 0.0,
                                     published_templates=published,
                                     strict_templates=strict)


def lines(rows, template):
    """'[section] food amt x unit' for each ingredient of [template]."""
    return [f"[{r['section']}] {r['component_label']} "
            f"{float(r['portion_amt']):.4g} x {r['unit_label']}"
            for r in rows
            if r.get("template_name") == template and r.get("_type") == "data"]


def kcal(rows, template):
    return round(sum(r["cal_tot"] for r in rows if r.get("template_name") == template
                     and r.get("_type") == "data"), 1)


# ── Serving size ────────────────────────────────────────────────────────────

def test_dashi_stock_is_per_cup(tmp_path, foods):
    rows = run(tmp_path, DASHI_STOCK)
    assert lines(rows, "Dashi Stock") == [
        "[Main] water 1 x cup", "[Main] dashi powder 1 x 1 tsp"]
    assert kcal(rows, "Dashi Stock") == 12.5


@pytest.mark.parametrize("line, servings", [
    ("1 cup dashi stock", 1),
    ("2 tbsp dashi stock", 0.125),
    ("250 ml dashi stock", 250 / 236.588),
    ("1 serving dashi stock", 1),
    ("1.5 cups Dashi Stock", 1.5),
])
def test_amount_over_serving_size(tmp_path, foods, line, servings):
    rows = run(tmp_path, DASHI_STOCK, f"Soup\nServings: 1\n{line}")
    assert lines(rows, "Soup") == [
        f"[Dashi Stock] water {servings:.4g} x cup",
        f"[Dashi Stock] dashi powder {servings:.4g} x 1 tsp"]


def test_the_recipe_servings_divide_it(tmp_path, foods):
    rows = run(tmp_path, DASHI_STOCK, "Miso Soup\nServings: 4\n4 cup dashi stock\n3 tbsp white miso")
    assert lines(rows, "Miso Soup") == [
        "[Dashi Stock] water 1 x cup",
        "[Dashi Stock] dashi powder 1 x 1 tsp",
        "[Main] white miso 0.75 x tbsp"]


def test_aka_names_and_repeats_share_one_section(tmp_path, foods):
    rows = run(tmp_path, DASHI_STOCK,
               "Ramen\nServings: 1\n1.5 cup dashi stock\n2 tbsp dashi\n0.5 cup dashi broth")
    assert lines(rows, "Ramen") == [
        "[Dashi Stock] water 2.125 x cup",
        "[Dashi Stock] dashi powder 2.125 x 1 tsp"]
    assert kcal(rows, "Ramen") == pytest.approx(2.125 * 12.5, abs=0.1)


def test_count_templates(tmp_path, foods):
    pork = "Braised Pork Belly\nServings: 8\nServing size: 1 slice\n8 slice pork belly"
    rows = run(tmp_path, pork, "Ramen\nServings: 1\n2 slice braised pork belly")
    assert lines(rows, "Ramen") == ["[Braised Pork Belly] pork belly 2 x slice"]


def test_grams_use_the_template_weight(tmp_path, foods):
    pork = "Braised Pork Belly\nServings: 8\nServing size: 1 slice\n8 slice pork belly"
    rows = run(tmp_path, pork, "Ramen\nServings: 1\n60 g braised pork belly")
    assert lines(rows, "Ramen") == ["[Braised Pork Belly] pork belly 2 x slice"]


# ── Nesting ─────────────────────────────────────────────────────────────────

def test_nested_templates_merge_into_one_section(tmp_path, foods):
    miso = "Miso Soup\nServings: 4\nServing size: 1 cup\n4 cup dashi stock\n3 tbsp white miso"
    rows = run(tmp_path, DASHI_STOCK, miso, "Set Meal\nServings: 2\n2 cup miso soup")
    assert lines(rows, "Set Meal") == [
        "[Miso Soup] water 1 x cup",
        "[Miso Soup] dashi powder 1 x 1 tsp",
        "[Miso Soup] white miso 0.75 x tbsp"]


# ── Not templates ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("line, food", [
    ("1 tsp dashi powder", "dashi powder"),
    ("1 cup water", "water"),
])
def test_other_names_are_still_foods(tmp_path, foods, line, food):
    rows = run(tmp_path, DASHI_STOCK, f"Soup\nServings: 1\n{line}")
    assert [r["component_label"] for r in rows
            if r.get("template_name") == "Soup" and r.get("_type") == "data"] == [food]
    assert all(r["section"] == "Main" for r in rows if r.get("template_name") == "Soup"
               and r.get("_type") == "data")


def test_a_near_miss_is_reported(tmp_path, foods):
    run(tmp_path, DASHI_STOCK, "Soup\nServings: 1\n1 cup dashi stok")
    assert any("dashi stok" in w and "Dashi Stock" in w
               for w in matcher.LAST_TEMPLATE_WARNINGS)


# ── Errors ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("blocks, message", [
    (("Braised Pork Belly\nServings: 8\nServing size: 1 slice\n8 slice pork belly",
      "Ramen\nServings: 1\n1 cup braised pork belly"), "write it in slice"),
    (("Dashi Stock\nServings: 4\n4 cup water",
      "Soup\nServings: 1\n1 cup dashi stock"), "has no Serving size"),
    (("Soup\nServings: 1\n1 cup dashi stock", DASHI_STOCK), "before its block"),
])
def test_unusable_lines_fail_the_run(tmp_path, foods, blocks, message):
    with pytest.raises(tref.TemplateReferenceError, match=message):
        run(tmp_path, *blocks)


def test_not_strict_falls_back_to_a_food(tmp_path, foods):
    pork = "Braised Pork Belly\nServings: 8\nServing size: 1 slice\n8 slice pork belly"
    rows = run(tmp_path, pork, "Ramen\nServings: 1\n1 cup braised pork belly", strict=False)
    assert [r["section"] for r in rows if r.get("template_name") == "Ramen"
            and r.get("_type") == "data"] == ["Main"]
    assert any("write it in slice" in w for w in matcher.LAST_TEMPLATE_WARNINGS)


def test_slug_lines_are_refused():
    with pytest.raises(parse_recipe.RecipeFormatError, match="1 cup dashi stock"):
        parse_recipe.parse_single_block(["Soup", "0.25 dashi_stock"], name_hint="x")


# ── Published templates (the recipe worker) ─────────────────────────────────

def test_a_published_template_is_copied(tmp_path, foods):
    published = tref.TemplateRef(
        tid="dashi_stock", name="Dashi Stock", aka=["Dashi broth"],
        serving_qty=1.0, serving_unit="cup", source="published",
        rows=[{"_type": "data", "_source": "branded", "component_label": "dashi powder",
               "food_id": "B_2381716", "portion_id": "tpl-dashi_stock-2",
               "portion_amt": 1.0, "unit_label": "tsp", "unit_grams": 4.0,
               "calories_kcal": 12.5, "cal_tot": 12.5, "section": "Main"}])
    rows = run(tmp_path, "Soup\nServings: 1\n1.5 cup dashi broth",
               published=[published], strict=False)
    assert lines(rows, "Soup") == ["[Dashi Stock] dashi powder 1.5 x tsp"]
    assert kcal(rows, "Soup") == pytest.approx(18.75, abs=0.1)


def test_this_runs_templates_win_over_published_ones(tmp_path, foods):
    stale = tref.TemplateRef(tid="old", name="Dashi Stock", serving_qty=1.0,
                             serving_unit="cup", source="published", rows=[])
    rows = run(tmp_path, DASHI_STOCK, "Soup\nServings: 1\n1 cup dashi stock",
               published=[stale])
    assert lines(rows, "Soup")[0].startswith("[Dashi Stock] water")


# ── Same name, two cuisines ─────────────────────────────────────────────────

def run_cuisines(tmp_path, *blocks):
    """[(category, block), ...] in one run, as two recipe files would be."""
    recipes = [parse_recipe.parse_single_block(b.split("\n"), name_hint="recipe",
                                               sticky_category=cat)
               for cat, b in blocks]
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv(recipes, str(csv), append=False)
    return matcher.build_output_rows(str(csv), POWDER_TSP, 0.0)


STOCK_WATER = "Soup Stock\nServings: 1\nServing size: 1 cup\n1 cup water"
STOCK_MISO = ("Soup Stock\nID: soup_stock_01\nServings: 1\nServing size: 1 cup\n"
              "1 tbsp white miso")


def test_a_recipe_uses_its_own_cuisines_template(tmp_path, foods):
    # Listed first, the Japanese stock used to win for every cuisine.
    rows = run_cuisines(tmp_path,
                        ("Japanese", STOCK_WATER),
                        ("Filipino", STOCK_MISO),
                        ("Filipino", "Sinigang\nServings: 1\n1 cup soup stock"),
                        ("Japanese", "Nabe\nServings: 1\n1 cup soup stock"))
    assert lines(rows, "Sinigang") == ["[Soup Stock] white miso 1 x tbsp"]
    assert lines(rows, "Nabe") == ["[Soup Stock] water 1 x cup"]


def test_another_cuisines_template_is_used_when_its_own_has_none(tmp_path, foods):
    rows = run_cuisines(tmp_path,
                        ("Japanese", DASHI_STOCK),
                        ("Filipino", "Misua Soup\nServings: 1\n1 cup dashi stock"))
    assert lines(rows, "Misua Soup")[0].startswith("[Dashi Stock] water")


def test_published_templates_carry_their_cuisine():
    japanese = tref.TemplateRef(tid="a", name="Soup Stock", category="Japanese")
    filipino = tref.TemplateRef(tid="b", name="Soup Stock", category="Filipino")
    refs = [japanese, filipino]
    index, by_cuisine = tref.build_index(refs), tref.build_cuisine_index(refs)
    assert tref.find("soup stock", "Filipino", index, by_cuisine) is filipino
    assert tref.find("soup stocks", "japanese", index, by_cuisine) is japanese
    assert tref.find("soup stock", "", index, by_cuisine) is japanese
    assert tref.find("soup stock", "Korean", index, by_cuisine) is japanese


@pytest.mark.parametrize("name, key", [
    ("Ramen Eggs", "ramen egg"), ("Dashi-Stock", "dashi stock"),
    ("Sauces", "sauce"), ("glass", "glass"),
])
def test_template_keys(name, key):
    assert tref.template_key(name) == key
