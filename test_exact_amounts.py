"""Same-kind units convert by exact ratios, not through grams.

Portion weights are rounded or slightly off, so dividing a recipe's grams by
them gave near misses the app can't show as a fraction: Yakitori's 1/4 cup
mirin over 8 servings was 0.493 tbsp, a 1.5 lb chicken thigh line 0.88
thigh, and Chashu Pork's sake 0.018 fl oz. Grams are only for calories.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher


def rows_for(tmp_path, monkeypatch, food, *lines, servings=1):
    monkeypatch.setattr(matcher, "match_ingredient",
                        lambda *a, **k: (food, 1.0, "high", None))
    meta, ings = parse_recipe.parse_single_block(
        ["Test", f"Servings: {servings}", "", "Ingredients", *lines],
        name_hint="recipe", category_override="Main")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    rows = matcher.build_output_rows(str(csv), [], 0.0)
    return [r for r in rows if r.get("_type") == "data"]


def usda_food(*portions, category=""):
    return {"source": "usda", "row": 0, "fdc_id": "1", "display_name": "Food",
            "energy_kcal": 100.0, "category": category,
            "portions": [{"portion_id": f"1-{i}", "label": label, "gram_weight": grams,
                          "gram_col": "", "portion_idx": i}
                         for i, (label, grams) in enumerate(portions, start=1)]}


# Live MIRIN SWEET COOKING RICE WINE (B_2570531): "2 tbsp. (30ml)", 30 g.
MIRIN = matcher._build_supabase_branded_food(
    {"id": 1, "fdc_id": 2570531, "source_set": "branded", "description": "MIRIN",
     "display_name": "MIRIN", "calories_100g": 150, "serving_size": 30.0,
     "serving_size_unit": "ml", "household_serving_full_text": "2 tbsp. (30ml)"},
    0, {})


def test_mirin_quarter_cup_over_eight_is_half_a_tbsp(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, MIRIN, "1/4 cup mirin", servings=8)
    assert row["unit_label"] == "2 tbsp. (30ml)"
    # A quarter of the 2 tbsp serving: 1/2 tbsp, not 0.4929.
    assert row["portion_amt"] == pytest.approx(0.25, abs=1e-9)
    assert row["cal_tot"] == pytest.approx(11.2, abs=0.1)


def test_two_thirds_cup_over_four_is_exactly_a_sixth(tmp_path, monkeypatch):
    # 2/3 used to be kept to 4 places (0.6667), and 1/6 cup became 2.6668 tbsp.
    food = usda_food(("1 tbsp", 7.8125))
    [row] = rows_for(tmp_path, monkeypatch, food, "2/3 cup flour", servings=4)
    assert row["portion_amt"] == pytest.approx(8 / 3, abs=1e-9)


def test_pounds_become_ounces_by_ratio(tmp_path, monkeypatch):
    # USDA's "oz" is 28.25 g; 1.5 lb over 8 is still exactly 3 of them.
    food = usda_food(("1 thigh", 193.0), ("1 oz", 28.25))
    [row] = rows_for(tmp_path, monkeypatch, food, "1.5 lb chicken thigh", servings=8)
    assert row["unit_label"] == "1 oz"
    assert row["portion_amt"] == pytest.approx(3.0, abs=1e-9)


def test_a_weight_portion_with_another_count_converts_by_ratio(tmp_path, monkeypatch):
    food = usda_food(("4 oz", 113.0))
    [row] = rows_for(tmp_path, monkeypatch, food, "1.5 lb chicken thigh", servings=8)
    assert row["unit_label"] == "4 oz"
    assert row["portion_amt"] == pytest.approx(0.75, abs=1e-9)


def test_a_weight_line_prefers_ounces_over_a_count(tmp_path, monkeypatch):
    # No oz portion: 1 oz is worked out, rather than 0.88 thigh.
    food = usda_food(("1 thigh with skin", 193.0))
    [row] = rows_for(tmp_path, monkeypatch, food, "1.5 lb chicken thigh", servings=4)
    assert row["unit_label"] == "1 oz"
    assert row["unit_grams"] == pytest.approx(28.349523125)
    assert row["portion_amt"] == pytest.approx(6.0, abs=1e-9)
    assert row["cal_tot"] == pytest.approx(170.1, abs=0.5)


def test_a_lb_portion_still_reads_in_ounces(tmp_path, monkeypatch):
    food = usda_food(("1 lb", 453.6))
    [row] = rows_for(tmp_path, monkeypatch, food, "2 lb pork belly", servings=16)
    assert row["unit_label"] == "1 oz"
    assert row["portion_amt"] == pytest.approx(2.0, abs=1e-9)


def test_an_oz_yields_label_is_not_a_weight():
    assert matcher._label_measure({"label": "1 oz yields", "gram_weight": 20.0}) is None
    assert matcher._label_measure({"label": "2 tbsp. (30ml)", "gram_weight": 30.0}) == (
        2.0, "tbsp", "volume")
    assert matcher._label_measure({"label": "serving 8 fl oz", "gram_weight": 240.0}) is None


def test_tiny_fl_oz_steps_down_to_tsp(tmp_path, monkeypatch):
    # 1 tbsp over 16 is 1/32 fl oz and 1/16 tbsp; both under 1/8.
    food = usda_food(("1 fl oz", 29.1))
    [row] = rows_for(tmp_path, monkeypatch, food, "1 tbsp rice wine", servings=16)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(3 / 16, abs=1e-9)
    assert row["unit_grams"] == pytest.approx(29.1 / 6)


def test_tiny_cup_of_a_branded_paste_steps_down_to_tbsp(tmp_path, monkeypatch):
    food = matcher._build_supabase_branded_food(
        {"id": 1, "fdc_id": 2030253, "source_set": "branded", "description": "RED BEAN",
         "display_name": "RED BEAN", "calories_100g": 272, "serving_size": 103.0,
         "serving_size_unit": "g", "household_serving_full_text": "0.33 cup"},
        0, {})
    [row] = rows_for(tmp_path, monkeypatch, food, "1/4 cup red bean paste", servings=4)
    assert row["unit_label"] == "1 tbsp"
    assert row["portion_amt"] == pytest.approx(1.0, abs=1e-9)


def test_under_an_eighth_tsp_stays_tsp(tmp_path, monkeypatch):
    food = usda_food(("1 tsp", 6.0))
    [row] = rows_for(tmp_path, monkeypatch, food, "1/4 tsp salt", servings=4)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(1 / 16, abs=1e-9)


def test_chopped_cups_do_not_step_down(tmp_path, monkeypatch):
    # A spoon can't be worked out from a cup of chunks.
    food = usda_food(("1 cup, chopped", 89.0), category="Vegetables and Vegetable Products")
    [row] = rows_for(tmp_path, monkeypatch, food, "1 cup cabbage", servings=16)
    assert row["unit_label"] == "1 cup, chopped"
    assert row["portion_amt"] == pytest.approx(1 / 16, abs=1e-9)


def test_a_tbsp_of_oil_steps_down_whatever_its_category(tmp_path, monkeypatch):
    # "Salad dressings and vegetable oils" reads as produce to the cup rule.
    food = usda_food(("1 cup", 224.0), ("1 tablespoon", 14.0),
                     category="Salad dressings and vegetable oils")
    [row] = rows_for(tmp_path, monkeypatch, food, "1 tsp sesame oil", servings=4)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(0.25, abs=1e-9)
