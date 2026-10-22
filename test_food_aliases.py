"""Names USDA keeps in a food's portions (food_aliases, 22 Oct 2026).

"Pasta, cooked, enriched" has "cup penne" (107 g); "Bread, French or Vienna"
has "1 baguette" (324 g). In the Italian trial "cooked spaghetti" matched
canned spaghetti rings and "cooked penne" nothing. Supabase is stubbed, so
these run offline.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher

# Live values (Supabase, 22 Oct 2026).
PASTA_PORTIONS = [
    {"label": "cup spaghetti not packed", "grams": 124.0, "sequence_number": 1},
    {"label": "cup spaghetti packed", "grams": 151.0, "sequence_number": 2},
    {"label": "cup penne", "grams": 107.0, "sequence_number": 3},
]
BREAD_PORTIONS = [
    {"label": "1 medium or regular slice", "grams": 64, "sequence_number": 1},
    {"label": "1 mini baguette (about 9\" long)", "grams": 152, "sequence_number": 2},
    {"label": "1 baguette (about 22\" long)", "grams": 324, "sequence_number": 3},
]
PASTA = matcher._build_supabase_usda_food(
    {"id": 2589, "fdc_id": 169737, "source_set": "sr_legacy",
     "description": "Pasta, cooked, enriched, without added salt",
     "display_name": "Pasta, cooked, enriched, without added salt",
     "calories_100g": 158},
    0, {2589: PASTA_PORTIONS})
BREAD = matcher._build_supabase_usda_food(
    {"id": 465842, "fdc_id": 2707610, "source_set": "survey_fndds_food",
     "description": "Bread, French or Vienna", "display_name": "Bread, French or Vienna",
     "calories_100g": 272},
    0, {465842: BREAD_PORTIONS})
SPAGHETTI_RINGS = {"name": "SPAGHETTI RINGS", "display_name": "SPAGHETTI RINGS",
                   "fdc_id": "B_1", "source": "branded", "energy_kcal": 80.0,
                   "portions": [{"portion_id": "B_1-1", "label": "1 cup", "gram_weight": 242.0,
                                 "gram_col": "", "portion_idx": 1}]}

ALIASES = [
    {"alias": "cooked spaghetti", "unit": "cup",
     "food": {"fdc_id": 169737, "source_set": "sr_legacy"}, "portion": PASTA_PORTIONS[0]},
    {"alias": "cooked penne", "unit": "cup",
     "food": {"fdc_id": 169737, "source_set": "sr_legacy"}, "portion": PASTA_PORTIONS[2]},
    {"alias": "baguette", "unit": "piece",
     "food": {"fdc_id": 2707610, "source_set": "survey_fndds_food"}, "portion": BREAD_PORTIONS[2]},
    {"alias": "mini baguette", "unit": "piece",
     "food": {"fdc_id": 2707610, "source_set": "survey_fndds_food"}, "portion": BREAD_PORTIONS[1]},
]


@pytest.fixture
def stubbed(monkeypatch):
    searched = []

    def fake_match(ingredient, *a, **k):
        searched.append(ingredient)
        if "spaghetti" in ingredient:
            return SPAGHETTI_RINGS, 2.0, "high", None
        return None, 0.0, "none", None

    monkeypatch.setattr(matcher, "match_ingredient", fake_match)
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    monkeypatch.setattr(matcher, "load_food_aliases", lambda: ALIASES)
    monkeypatch.setattr(matcher, "_FOOD_ALIASES", {})
    monkeypatch.setattr(matcher, "_FOOD_ALIASES_TRIED_AT", None)
    foods = {"169737": PASTA, "2707610": BREAD}
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id", lambda fdc: foods.get(fdc))
    return searched


def run(tmp_path, block):
    recipe = parse_recipe.parse_single_block(block.split("\n"), name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([recipe], str(csv), append=False)
    return [r for r in matcher.build_output_rows(str(csv), [], 0.0) if r.get("_type") == "data"]


def row(rows, label):
    return next(r for r in rows if r["component_label"] == label)


def test_cooked_spaghetti_is_plain_pasta_not_spaghetti_rings(tmp_path, stubbed):
    r = row(run(tmp_path, "X\nServings: 1\n1 cup cooked spaghetti"), "cooked spaghetti")
    assert r["matched_food_name"] == "Pasta, cooked, enriched, without added salt"
    assert r["unit_grams"] == 124.0
    assert r["cal_tot"] == pytest.approx(1.24 * 158, abs=0.5)
    assert "[ALIAS]" in r["notes"]
    assert stubbed == []  # never searched


def test_each_shape_uses_its_own_cup(tmp_path, stubbed):
    r = row(run(tmp_path, "X\nServings: 2\n3 cup cooked penne"), "cooked penne")
    assert r["unit_grams"] == 107.0
    assert float(r["portion_amt"]) == pytest.approx(1.5)


def test_baguette_counts_and_the_mini_one_by_its_size_word(tmp_path, stubbed):
    rows = run(tmp_path, "X\nServings: 1\n1 baguette\n1/2 mini baguette")
    assert [r["unit_grams"] for r in rows] == [324.0, 152.0]


def test_another_unit_keeps_the_food_but_not_the_portion(tmp_path, stubbed):
    # USDA has no baguette slice; the sandwich-loaf slice is what's left.
    r = row(run(tmp_path, "X\nServings: 1\n2 slice baguette"), "baguette")
    assert r["matched_food_name"] == "Bread, French or Vienna"
    assert r["unit_grams"] == 64.0


DRY_LINGUINE = {"display_name": "LINGUINE", "raw_description": "LINGUINE",
                "fdc_id": "B_2", "source": "branded", "energy_kcal": 357.0, "row": {},
                "portions": [{"portion_id": "B_2-1", "label": "2 oz", "gram_weight": 56.0,
                              "gram_col": "", "portion_idx": 1}]}


def test_dry_pasta_by_weight_is_not_doubled(tmp_path, monkeypatch, stubbed):
    # The 2x raw-to-cooked factor is for a cooked food; branded pasta is dry.
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda ing, *a, **k: (DRY_LINGUINE, 2.3, "high", None))
    r = row(run(tmp_path, "X\nServings: 1\n8 oz uncooked linguine"), "uncooked linguine")
    assert "[yield" not in r["notes"]
    assert r["cal_tot"] == pytest.approx(226.8 / 100 * 357, rel=0.02)


def test_pasta_by_weight_onto_a_cooked_food_still_gets_its_yield(tmp_path, monkeypatch, stubbed):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda ing, *a, **k: (PASTA, 1.0, "high", None))
    r = row(run(tmp_path, "X\nServings: 1\n4 oz linguine"), "linguine")
    assert "[yield 2.0]" in r["notes"]


def test_a_cooked_shape_with_no_cooked_food_is_its_dry_pasta(tmp_path, monkeypatch, stubbed):
    # USDA cooks only some shapes; 1 cup cooked is about 2 oz dry.
    def fake(ing, *a, **k):
        return (DRY_LINGUINE, 2.3, "high", None) if ing == "linguine" else (None, 0.0, "none", None)
    monkeypatch.setattr(matcher, "match_ingredient", fake)
    r = row(run(tmp_path, "X\nServings: 2\n3 cup cooked linguine"), "cooked linguine")
    assert r["matched_food_name"] == "LINGUINE"
    assert "[DRY, from cooked]" in r["notes"]
    # 3 cups for 2 servings: 3 oz dry each.
    assert r["cal_tot"] == pytest.approx(3 * 28.35 / 100 * 357, rel=0.02)


def test_cooked_pasta_by_weight_on_a_dry_product_is_its_dry_weight(tmp_path, monkeypatch, stubbed):
    # By weight a dry product can win outright; 1 lb cooked was counted as 1 lb dry.
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda ing, *a, **k: (DRY_LINGUINE, 2.1, "high", None))
    r = row(run(tmp_path, "X\nServings: 1\n1 lb cooked linguine"), "cooked linguine")
    assert "[DRY, from cooked]" in r["notes"]
    assert r["cal_tot"] == pytest.approx(453.6 / 2.35 / 100 * 357, rel=0.02)


def test_names_without_an_alias_match_as_before(tmp_path, stubbed):
    r = row(run(tmp_path, "X\nServings: 1\n1 cup cooked quinoa"), "cooked quinoa")
    assert r["_confidence"] == "none"
    assert stubbed == ["cooked quinoa"]
