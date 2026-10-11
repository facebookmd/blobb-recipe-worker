"""Branded foods read their label serving, and calories scale with grams.

Branded foods have no food_portions rows; the serving is on the foods row
(serving_size, serving_size_unit, household_serving_full_text), and
energy_kcal is calories_100g. "2 tbsp gyoza dipping sauce" used to come out
as 2 x 100 g (266 kcal), and every override as the per-100 g figure.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import parse_recipe
import recipe_matcher as matcher


def branded_row(fdc_id, kcal, size, unit, household, row_id=1):
    """A foods row shaped like the live branded rows."""
    return {"id": row_id, "fdc_id": fdc_id, "source_set": "branded",
            "description": f"FOOD {fdc_id}", "display_name": f"FOOD {fdc_id}",
            "calories_100g": kcal, "serving_size": size,
            "serving_size_unit": unit, "household_serving_full_text": household}


def build(row):
    return matcher._build_supabase_branded_food(row, 0, {})


# Live values (Supabase, 11 Oct 2026).
GYOZA = branded_row(2297219, 133, 30.0, "ml", "2 Tbsp")
RED_BEAN = branded_row(2030253, 272, 103.0, "g", "0.33 cup")
TEMPURA = branded_row(2085146, 100, 5.0, "ml", "1 tsp")
DASHI = branded_row(2552927, 312, 8.0, "GRM", "0.28 oz")
TAMARIND = branded_row(2116522, 200, 4.0, "g", "4 GRM")


def test_the_label_serving_becomes_a_portion():
    food = build(GYOZA)
    assert [(p["label"], p["gram_weight"], p["portion_idx"]) for p in food["portions"]] == [
        ("100g", 100.0, 0), ("2 tbsp", 30.0, 1)]


@pytest.mark.parametrize("row, label", [
    (RED_BEAN, "0.33 cup"),
    (TEMPURA, "1 tsp"),
    (DASHI, "1 serving"),     # a weight is never read as a volume
    (TAMARIND, "1 serving"),
    (branded_row(1, 250, 40.0, "g", "1 BAR"), "1 bar"),
    (branded_row(1, 250, 40.0, "g", ""), "1 serving"),
])
def test_serving_labels(row, label):
    assert build(row)["portions"][1]["label"] == label


@pytest.mark.parametrize("row", [
    branded_row(1, 250, None, "g", "2 Tbsp"),
    branded_row(1, 250, 2.0, "oz", "2 oz"),
    branded_row(1, 250, 100.0, "g", "1 cup"),  # the 100 g basis already covers it
])
def test_no_serving_when_the_row_has_no_usable_one(row):
    assert len(build(row)["portions"]) == 1


def test_food_portions_rows_win_over_the_foods_row():
    food = matcher._build_supabase_branded_food(
        GYOZA, 0, {1: [{"label": "1 cup", "grams": 240}]})
    assert [p["label"] for p in food["portions"]] == ["100g", "1 cup"]


def test_a_volume_serving_is_picked_for_a_spoon_line():
    food = build(GYOZA)
    assert matcher.pick_best_portion(food, "tbsp", None, 2.0)["label"] == "2 tbsp"


def test_a_weight_serving_does_not_beat_a_spoon_override():
    rules = [{"trigger": "dashi powder", "portion_gram_weight": 15,
              "portion_unit": "tbsp", "portion_label": "1 tbsp"}]
    portion = matcher.pick_best_portion(build(DASHI), "tbsp", None, 1.0,
                                        "dashi powder", rules)
    assert portion["gram_weight"] == 15


def test_a_weight_serving_still_serves_a_count_line():
    portion = matcher.pick_best_portion(build(TAMARIND), "serving", None, 1.0)
    assert portion["label"] == "1 serving"


# ── Through build_output_rows ─────────────────────────────────────────────

def rows_for(tmp_path, monkeypatch, line, food, rules=()):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda *a, **k: (food, 1.0, "high", None))
    meta, ings = parse_recipe.parse_single_block(
        ["Test", "", "Ingredients", line], name_hint="recipe",
        category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    rows = matcher.build_output_rows(str(csv), list(rules), 0.0)
    return [r for r in rows if r.get("_type") == "data"]


def test_two_tbsp_gyoza_sauce_is_one_label_serving(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, "2 tbsp gyoza dipping sauce", build(GYOZA))
    assert row["portion_description"] == "2 tbsp (30 g)"
    assert row["cal_tot"] == pytest.approx(39.9)


def test_red_bean_paste_scales_from_its_cup(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, "2 tbsp red bean paste", build(RED_BEAN))
    # 2 tbsp of a 0.33 cup (103 g) serving: 39 g at 272 kcal / 100 g.
    assert row["cal_tot"] == pytest.approx(106.1, abs=0.2)


@pytest.mark.parametrize("unit, grams", [("tsp", 5), ("tbsp", 15), ("cup", 240)])
def test_override_calories_follow_its_grams(tmp_path, monkeypatch, unit, grams):
    rules = [{"trigger": "dashi powder", "portion_gram_weight": grams,
              "portion_unit": unit, "portion_label": f"1 {unit}"}]
    [row] = rows_for(tmp_path, monkeypatch, f"1 {unit} dashi powder",
                     build(DASHI), rules)
    assert row["calories_kcal"] == pytest.approx(grams / 100 * 312, abs=0.1)
    assert row["cal_tot"] == pytest.approx(grams / 100 * 312, abs=0.1)


@pytest.mark.parametrize("line, label, amount", [
    ("1/4 cup tempura dipping sauce", "1 cup (240.0 g)", 0.25),  # a US cup
    ("1/8 cup tempura dipping sauce", "1 tbsp (15.0 g)", 2.0),  # small: spoons
    ("1 tbsp tempura dipping sauce", "1 tbsp (15.0 g)", 1.0),
    ("2 tsp tempura dipping sauce", "1 tsp (5 g)", 2.0),        # already a tsp
])
def test_a_spoon_serving_follows_the_recipe_spoon(tmp_path, monkeypatch,
                                                  line, label, amount):
    [row] = rows_for(tmp_path, monkeypatch, line, build(TEMPURA))
    assert row["portion_description"] == label
    assert row["portion_amt"] == pytest.approx(amount)
    grams = {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}[label.split()[1]]
    assert row["cal_tot"] == pytest.approx(amount * grams)  # 100 kcal / 100 g


def test_a_tbsp_serving_converts_to_tsp(tmp_path, monkeypatch):
    tonkatsu = build(branded_row(2455990, 167, 15.0, "ml", "1 Tbsp"))
    [row] = rows_for(tmp_path, monkeypatch, "1 tsp tonkatsu sauce", tonkatsu)
    assert row["portion_description"] == "1 tsp (5.0 g)"
    assert row["cal_tot"] == pytest.approx(8.4, abs=0.1)


def test_many_cups_stay_cups(tmp_path, monkeypatch):
    # 3/4 cup; the sanity check used to swap 12 tbsp to 100 g x 1.8.
    [row] = rows_for(tmp_path, monkeypatch, "3/4 cup tempura dipping sauce", build(TEMPURA))
    assert row["portion_description"] == "1 cup (240.0 g)"
    assert row["portion_amt"] == pytest.approx(0.75)
    assert row["cal_tot"] == pytest.approx(180.0)


def test_the_sanity_check_never_picks_the_100g_basis(tmp_path, monkeypatch):
    # 500 g is 125 label servings; it stays on the serving, not 100 g x 5.
    [row] = rows_for(tmp_path, monkeypatch, "500 g tamarind soup mix", build(TAMARIND))
    assert row["portion_description"] == "1 serving (4 g)"
    assert row["cal_tot"] == pytest.approx(1000.0)


def test_the_sanity_check_still_fixes_a_poor_fit(tmp_path, monkeypatch):
    def usda(pid, label, grams):
        return {"portion_id": pid, "label": label, "gram_weight": grams,
                "gram_col": "", "portion_idx": 1}
    food = {"source": "usda", "row": 0, "fdc_id": "1", "display_name": "Candy",
            "energy_kcal": 400.0,
            "portions": [usda("1-1", "1 piece", 2.0), usda("1-2", "1 bag", 400.0)]}
    [row] = rows_for(tmp_path, monkeypatch, "800 g candy", food)
    assert row["portion_description"] == "1 bag (400 g)"
    assert row["portion_amt"] == pytest.approx(2.0)


def usda_food(*portions):
    return {"source": "usda", "row": 0, "fdc_id": "1", "display_name": "Food",
            "energy_kcal": 100.0,
            "portions": [{"portion_id": f"1-{i}", "label": label, "gram_weight": grams,
                          "gram_col": "", "portion_idx": i}
                         for i, (label, grams) in enumerate(portions, start=1)]}


def test_spoons_in_the_recipe_unit_stay_put(tmp_path, monkeypatch):
    food = usda_food(("1 tbsp", 14.0), ("1 cup", 227.0))
    [row] = rows_for(tmp_path, monkeypatch, "12 tbsp butter", food)
    assert row["portion_description"] == "1 tbsp (14 g)"
    assert row["portion_amt"] == pytest.approx(12.0)


def test_a_far_off_volume_still_moves(tmp_path, monkeypatch):
    # 1 gallon against a fl oz portion is 128 fl oz; a liter reads better.
    food = usda_food(("1 fl oz", 30.0), ("1 liter", 1000.0))
    [row] = rows_for(tmp_path, monkeypatch, "1 gallon water", food)
    assert row["portion_description"] == "1 liter (1000 g)"


def test_the_100g_basis_is_calories_100g(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, "200 g gyoza dipping sauce", build(GYOZA))
    assert row["cal_tot"] == pytest.approx(266.0)


# ── Live Supabase ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                    reason="needs SUPABASE_ANON_KEY (live Supabase)")
def test_live_gyoza_sauce(tmp_path):
    meta, ings = parse_recipe.parse_single_block(
        ["Test", "", "Ingredients", "2 tbsp gyoza dipping sauce"],
        name_hint="recipe", category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    rows = matcher.build_output_rows(str(csv), matcher.load_boosts("boosts.json"), 0.0)
    [row] = [r for r in rows if r.get("_type") == "data"]
    assert row["food_id"] == "B_2297219"
    assert row["cal_tot"] == pytest.approx(39.9, abs=1)


# ── Estimated portions (1 g/ml) ───────────────────────────────────────────

NO_SERVING = branded_row(9, 200, None, "g", "")
SALT_ONLY = branded_row(9, 200, 4.0, "g", "4 GRM")


@pytest.mark.parametrize("food_row", [NO_SERVING, SALT_ONLY])
@pytest.mark.parametrize("line, label, amount", [
    ("2 tbsp mystery sauce", "1 tbsp (15 g)", 2.0),
    ("1 tsp mystery sauce", "1 tsp (5 g)", 1.0),
    ("1/4 cup mystery sauce", "1 cup (236.6 g)", 0.25),  # a cup at 1 g/ml
])
def test_a_spoon_line_with_no_volume_portion_is_estimated(
        tmp_path, monkeypatch, food_row, line, label, amount):
    [row] = rows_for(tmp_path, monkeypatch, line, build(food_row))
    assert row["estimated"] is True
    assert row["portion_description"] == label
    assert row["portion_amt"] == pytest.approx(amount)
    grams = amount * matcher._volume_to_ml(1.0, label.split()[1])
    assert row["cal_tot"] == pytest.approx(grams / 100 * 200, abs=0.2)
    assert "PORTION NOT FOUND" in row["notes"]


@pytest.mark.parametrize("line", [
    "2 tbsp gyoza dipping sauce",   # a volume serving measures it
    "60 ml gyoza dipping sauce",    # ml converts to grams
    "30 g gyoza dipping sauce",
])
def test_lines_a_portion_can_measure_are_not_estimated(tmp_path, monkeypatch, line):
    [row] = rows_for(tmp_path, monkeypatch, line, build(GYOZA))
    assert row["estimated"] is False


def test_an_override_is_not_estimated(tmp_path, monkeypatch):
    rules = [{"trigger": "dashi powder", "portion_gram_weight": 15,
              "portion_unit": "tbsp", "portion_label": "1 tbsp"}]
    [row] = rows_for(tmp_path, monkeypatch, "1 tbsp dashi powder", build(DASHI), rules)
    assert row["estimated"] is False


def test_the_worker_names_estimated_ingredients(monkeypatch):
    import app as worker
    foods = {"mystery sauce": build(NO_SERVING), "gyoza dipping sauce": build(GYOZA)}
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda ingredient, *a, **k: (foods[ingredient], 1.0, "high", None))
    response = worker._match_recipe(
        "Test\n\nIngredients\n2 tbsp mystery sauce\n2 tbsp gyoza dipping sauce",
        0.0, "Main")
    assert response.estimated == ["mystery sauce"]


@pytest.mark.parametrize("line", ["1 packet tamarind soup mix", "2 sachets tamarind soup mix"])
def test_a_packet_without_a_packet_portion_is_flagged(tmp_path, monkeypatch, line):
    [row] = rows_for(tmp_path, monkeypatch, line, build(TAMARIND))
    assert row["estimated"] is True
    assert "PACKET PORTION NOT FOUND" in row["notes"]


def test_a_packet_portion_is_not_flagged(tmp_path, monkeypatch):
    food = usda_food(("1 packet", 4.2), ("1 tsp", 4.2))
    [row] = rows_for(tmp_path, monkeypatch, "2 packets sugar", food)
    assert row["portion_description"] == "1 packet (4 g)"
    assert row["estimated"] is False


# ── Packets: the label's package size ──────────────────────────────────────

@pytest.mark.parametrize("text, grams", [
    ("1.4 oz/40 g", 40.0), ("32 ONZ", 32 * 28.349523125), ("40 g", 40.0),
    ("1 LB", 453.59237), ("16 OZ/1 LB 454 g", 454.0), ("", None), ("1 packet", None),
])
def test_package_weight_in_grams(text, grams):
    if grams is None:
        assert matcher._package_grams(text) is None
    else:
        assert matcher._package_grams(text) == pytest.approx(grams)


def test_a_packet_is_the_package_not_one_serving(tmp_path, monkeypatch):
    # PAMANA tamarind soup mix: label serving 4 g, package 1.4 oz/40 g.
    food = build({**TAMARIND, "package_weight": "1.4 oz/40 g"})
    [row] = rows_for(tmp_path, monkeypatch, "1 packet tamarind soup mix", food)
    assert row["portion_description"] == "1 packet (40 g)"
    assert row["portion_amt"] == 1
    assert row["cal_tot"] == pytest.approx(80.0)
    assert not row["estimated"]
    assert "MISMATCH" not in row["notes"]


def test_without_a_package_weight_a_packet_is_still_an_estimate(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, "1 packet tamarind soup mix", build(TAMARIND))
    assert row["estimated"]
    assert "MISMATCH" not in row["notes"]


# ── Container cups: a "cup" that is the cup a food is sold in ──────────────

DOLE_WHIP = branded_row(1, 120, 108.0, "ml", "1 cup")       # live: 108 ml "cup"
ALOE = branded_row(2, 40, 160.0, "MLT", "1 cup")
MILK_CUP = branded_row(3, 60, 240.0, "MLT", "1 cup")
HALF_CUP = branded_row(4, 60, 120.0, "ml", "1/2 cup")
METRIC = branded_row(5, 60, 250.0, "ml", "1 cup")
CEREAL = branded_row(6, 380, 30.0, "g", "1 cup")


@pytest.mark.parametrize("row, label", [
    (DOLE_WHIP, "1 container"), (ALOE, "1 container"),
    (MILK_CUP, "1 cup"), (HALF_CUP, "1/2 cup"), (METRIC, "1 cup"),
    (CEREAL, "1 cup"),  # a gram serving can't be checked; trusted
])
def test_only_measuring_cups_stay_cups(row, label):
    assert build(row)["portions"][1]["label"] == label


def test_a_container_cup_is_never_converted(tmp_path, monkeypatch):
    # 2 tbsp is not worked out from the 108 ml cup it's sold in.
    [row] = rows_for(tmp_path, monkeypatch, "2 tbsp dole whip", build(DOLE_WHIP))
    assert row["estimated"]
    assert "container" not in row["portion_description"]
