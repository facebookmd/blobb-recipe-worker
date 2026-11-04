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


@pytest.mark.parametrize("line, servings, tsp", [
    ("1/4 tsp salt", 4, 1 / 16),
    ("1/8 tsp salt", 4, 1 / 32),
    ("1/4 tsp salt", 16, 1 / 64),
])
def test_under_an_eighth_tsp_stays_tsp(tmp_path, monkeypatch, line, servings, tsp):
    # No pinches (Arianna, 4 Nov 2026): the app shows 0.063 tsp and opens its keypad.
    food = usda_food(("1 tsp", 6.0))
    [row] = rows_for(tmp_path, monkeypatch, food, line, servings=servings)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(tsp, abs=1e-9)


def test_ground_pepper_and_teaspoon_labels_stay_tsp_too(tmp_path, monkeypatch):
    for label in ("tsp, ground", "1 teaspoon"):
        food = usda_food((label, 2.3))
        [row] = rows_for(tmp_path, monkeypatch, food, "1/8 tsp pepper", servings=4)
        assert row["unit_label"] == label
        assert row["portion_amt"] == pytest.approx(1 / 32, abs=1e-9)


def test_an_eighth_tsp_stays_tsp(tmp_path, monkeypatch):
    food = usda_food(("1 tsp", 6.0))
    [row] = rows_for(tmp_path, monkeypatch, food, "1/2 tsp salt", servings=4)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(1 / 8, abs=1e-9)


def test_tiny_counts_stay_counts(tmp_path, monkeypatch):
    food = usda_food(("1 large", 50.0))
    [row] = rows_for(tmp_path, monkeypatch, food, "1 large egg", servings=24)
    assert row["unit_label"] == "1 large"
    assert row["portion_amt"] == pytest.approx(1 / 24, abs=1e-9)


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


def test_small_tsp_calories_are_the_tsp_rows(tmp_path, monkeypatch):
    food = usda_food(("1 tsp", 5.3))   # soy sauce, 53 kcal / 100 g
    food["energy_kcal"] = 53.0
    [row] = rows_for(tmp_path, monkeypatch, food, "1.5 tsp soy sauce", servings=16)
    assert row["unit_label"] == "1 tsp"
    assert row["cal_tot"] == pytest.approx(round(2.8 * 1.5 / 16, 1))


# ── Units the wheel can show ──────────────────────────────────────────────

def test_an_off_wheel_tbsp_moves_to_tsp(tmp_path, monkeypatch):
    # 1 tbsp over 6 is 1/6 tbsp, which the wheel can't show: 1/2 tsp.
    food = usda_food(("1 fl oz", 29.1))
    [row] = rows_for(tmp_path, monkeypatch, food, "1 tbsp rice wine", servings=6)
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(1 / 2, abs=1e-9)


def test_three_eighths_tbsp_stays_in_tbsp(tmp_path, monkeypatch):
    # 1.5 tbsp over 4: 3/8 is on the wheel since 21 Oct.
    food = usda_food(("1 fl oz", 29.1))
    [row] = rows_for(tmp_path, monkeypatch, food, "1.5 tbsp rice wine", servings=4)
    assert row["unit_label"] == "1 tbsp"
    assert row["portion_amt"] == pytest.approx(3 / 8, abs=1e-9)


def test_an_off_wheel_cup_moves_to_tbsp(tmp_path, monkeypatch):
    # 3/4 cup over 4 is 3/16 cup: 3 tbsp.
    food = usda_food(("1 cup", 120.0), category="Cereal Grains and Pasta")
    [row] = rows_for(tmp_path, monkeypatch, food, "3/4 cup flour", servings=4)
    assert row["unit_label"] == "1 tbsp"
    assert row["portion_amt"] == pytest.approx(3.0, abs=1e-9)
    assert row["unit_grams"] * row["portion_amt"] == pytest.approx(22.5)


def test_an_amount_that_fits_nowhere_stays(tmp_path, monkeypatch):
    # 9/16 tsp is 3/16 tbsp: neither is on the wheel.
    food = usda_food(("1 tsp", 5.3))
    [row] = rows_for(tmp_path, monkeypatch, food, "3 tsp soy sauce", servings=16)
    assert (row["unit_label"], row["portion_amt"]) == ("1 tsp", pytest.approx(3 / 16))


def test_a_chunky_cup_does_not_move_to_spoons(tmp_path, monkeypatch):
    food = usda_food(("1 cup", 120.0), category="Vegetables and Vegetable Products")
    [row] = rows_for(tmp_path, monkeypatch, food, "3/4 cup cucumber", servings=4)
    assert row["unit_label"] == "1 cup"


def test_fits_wheel():
    assert matcher.fits_wheel(1.125) and matcher.fits_wheel(2 / 3) and matcher.fits_wheel(3)
    assert matcher.fits_wheel(0.375) and matcher.fits_wheel(1.625)   # 3/8, 5/8 (21 Oct)
    assert not matcher.fits_wheel(0.1875) and not matcher.fits_wheel(0.0625)


# ── Water ────────────────────────────────────────────────────────────────

from test_recipe_unit_volume import WATER  # noqa: E402


@pytest.mark.parametrize("line, servings, label, amount", [
    ("1/4 cup water", 4, "1 tbsp", 1.0),        # 1/16 cup
    ("1/4 cup water", 8, "1 tbsp", 0.5),        # 1/32 cup
    ("2/3 cup water", 4, "1 tbsp", 8 / 3),      # 1/6 cup
    ("1/4 cup water", 24, "1 tsp", 0.5),        # 1/96 cup
    ("1/2 cup water", 2, "1 ml", 62.5),         # 1/4 cup: ml from here up
    ("1 cup water", 1, "1 ml", 250.0),
])
def test_small_water_is_in_spoons(tmp_path, monkeypatch, line, servings, label, amount):
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    [row] = rows_for(tmp_path, monkeypatch, WATER, line, servings=servings)
    assert row["unit_label"] == label
    assert row["portion_amt"] == pytest.approx(amount, abs=1e-6)


def test_rice_wine_has_no_portion_override():
    # 17 g a tbsp was heavier than water; USDA's sake is 29.1 g a fl oz.
    rules = matcher.load_boosts("boosts.json")
    assert not [r for r in rules if r.get("trigger") == "rice wine"
                and r.get("portion_gram_weight")]


def test_water_copied_in_under_a_quarter_cup_is_in_spoons():
    # Dashi Stock's 250 ml of water, copied into Tamagoyaki x 1/16.
    row = {"_type": "data", "portion_id": "173647-1-ml", "unit_label": "1 ml",
           "unit_grams": 1.0009, "portion_amt": 15.625, "recipe_unit": "ml",
           "calories_kcal": 0.0}
    spoon = matcher._water_ml_to_spoons(row)
    assert (spoon["unit_label"], spoon["portion_amt"]) == ("1 tbsp", pytest.approx(1.0))
    assert matcher._water_ml_to_spoons({**row, "portion_amt": 62.5}) == {**row, "portion_amt": 62.5}
    tiny = matcher._water_ml_to_spoons({**row, "portion_amt": 1.0})
    assert tiny["unit_label"] == "1 tsp"


# FNDDS Soy sauce (2707442): no tsp, and a 2 g sushi guideline that the
# gram re-pick took for Chashu Pork's 1.5 tsp over 16 slices (4 Nov 2026).
SOY_SAUCE = usda_food(("Guideline amount per piece of sushi", 2.0), ("1 individual packet", 9.0),
                      ("1 tablespoon", 16.0), ("Quantity not specified", 16.0))


def test_a_small_volume_never_takes_the_sushi_guideline(tmp_path, monkeypatch):
    [row] = rows_for(tmp_path, monkeypatch, SOY_SAUCE, "1.5 tsp soy sauce", servings=16)
    assert "sushi" not in row["unit_label"] and "packet" not in row["unit_label"]
    # 3/32 tsp of a 16 g tablespoon, the same grams as before.
    assert row["unit_label"] == "1 tsp"
    assert row["portion_amt"] == pytest.approx(1.5 / 16, abs=1e-9)
    assert row["portion_amt"] * row["unit_grams"] == pytest.approx(16 / 3 * 1.5 / 16, abs=1e-6)


def test_the_guideline_is_never_a_label_for_a_gram_line(tmp_path, monkeypatch):
    # 1 g of soy sauce: closest in grams is the 2 g guideline, which nobody measures with.
    [row] = rows_for(tmp_path, monkeypatch, SOY_SAUCE, "1 g soy sauce")
    assert "Guideline" not in (row["portion_description"] or "")
