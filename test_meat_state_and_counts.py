"""Raw meat stays raw, cooked meat is cooked, and a count keeps the line's cut.

Arianna, 25 Nov 2026: what a line shows is what it is. A cooked cup is the
cooked row with its own calories; a raw line stays on the raw row. FNDDS meat
and fish rows are as eaten (cooked) though most don't say so: "Pork, ground"
is 299 kcal and 125 g a cup, raw ground pork 263 kcal with no cup.

Found 25 Nov 2026 (probe of count and cup lines):
  * "4 boneless skinless chicken thigh" matched raw chicken breast: the
    count fallback borrowed a relative's "piece" with "thigh" dropped.
  * "2 cup ground pork" (raw) was FNDDS's cooked cup, 125 g, for a raw 225.
  * "2 cup cooked ground pork" lost the cup (SR's cooked row has none).
  * "4 slice cooked pork belly" kept the "pork belly" alias's raw row, 1 RACC.

Run: .venv/bin/python -m pytest -q test_meat_state_and_counts.py
"""

from __future__ import annotations

import pytest

import parse_recipe
import recipe_matcher as matcher


def usda(food_id, fdc_id, source_set, data_type, description, display_name, kcal, portions):
    return matcher._build_supabase_usda_food(
        {"id": food_id, "fdc_id": fdc_id, "source_set": source_set, "data_type": data_type,
         "description": description, "display_name": display_name, "calories_100g": kcal},
        0, {food_id: [{"label": label, "value": 1.0, "grams": grams, "sequence_number": i}
                      for i, (label, grams) in enumerate(portions, start=1)]})


# Live values (Supabase, 25 Nov 2026). The ids are made up; fdc ids are real.
FNDDS = ("survey_fndds", "Survey (FNDDS)")
SR = ("sr_legacy", "SR Legacy")
FOUNDATION = ("foundation", "Foundation")

FNDDS_PORK_GROUND = usda(1, 2705863, *FNDDS, "Pork, ground", "Pork, ground", 299,
                         [("patty", 85.0), ("oz, raw (yields)", 20.0), ("cup", 125.0)])
SR_PORK_GROUND_RAW = usda(2, 167902, *SR, "Pork, fresh, ground, raw", "Ground pork, raw", 263,
                          [("oz", 113.0)])
SR_PORK_GROUND_COOKED = usda(3, 167903, *SR, "Pork, fresh, ground, cooked",
                             "Ground pork, cooked", 297, [("oz", 85.0)])
FNDDS_BEEF_GROUND_RAW = usda(4, 2705853, *FNDDS, "Beef, ground, raw", "Beef, ground, raw", 213,
                             [("cup", 225.0)])
FNDDS_PORK_BELLY = usda(5, 2705901, *FNDDS, "Pork, belly", "Pork, belly", 404,
                        [("slice, any size", 30.0), ("cup", 135.0)])
FOUNDATION_BELLY_SKIN = usda(6, 2727576, *FOUNDATION, "Pork, belly, with skin, raw",
                             "Pork belly, with skin, raw", 385, [("RACC", 26.0)])
SR_THIGH_STEWED_SKIN = usda(7, 173626, *SR,
                            "Chicken, broilers or fryers, thigh, meat and skin, cooked, stewed",
                            "Chicken thigh, with skin, stewed", 232, [("thigh, bone removed", 68.0)])
FNDDS_THIGH_STEWED_SKIN = usda(8, 2706037, *FNDDS, "Chicken thigh, stewed, skin eaten",
                               "Chicken thigh, stewed, skin eaten", 227,
                               [("cup, cooked, diced", 135.0), ("medium thigh", 90.0)])
SR_CHICKEN_STEWED_SKIN = usda(9, 171051, *SR, "Chicken, broilers or fryers, meat and skin, cooked, stewed",
                              "Chicken, with skin, stewed", 219, [("cup, chopped or diced", 140.0)])
FOUNDATION_THIGH_SKINLESS = usda(10, 2646171, *FOUNDATION, "Chicken, thigh, boneless, skinless, raw",
                                 "Chicken thigh, boneless, skinless, raw", 149, [("RACC", 114.0)])
SR_THIGH_SKINLESS_RAW = usda(11, 173627, *SR,
                             "Chicken, broilers or fryers, dark meat, thigh, meat only, raw",
                             "Chicken dark meat, thigh, skinless, raw", 121,
                             [("oz", 113.0), ("thigh without skin", 149.0)])
SR_THIGH_SKIN_RAW = usda(12, 172385, *SR, "Chicken, broilers or fryers, thigh, meat and skin, raw",
                         "Chicken thigh, with skin, raw", 221,
                         [("oz", 113.0), ("thigh with skin", 193.0)])
SR_BREAST_SKINLESS_RAW = usda(13, 171077, *SR,
                              "Chicken, broilers or fryers, breast, skinless, boneless, meat only, raw",
                              "Chicken breast, boneless, skinless, raw", 120, [("piece", 272.0)])


def test_fndds_meat_is_as_eaten_unless_it_says_raw():
    assert matcher._is_as_eaten_meat(FNDDS_PORK_GROUND)
    assert matcher._is_as_eaten_meat(FNDDS_PORK_BELLY)
    assert not matcher._is_as_eaten_meat(FNDDS_BEEF_GROUND_RAW)
    assert not matcher._is_as_eaten_meat(SR_PORK_GROUND_COOKED)  # SR, says cooked itself


def test_a_raw_row_is_not_fnddss_cooked_row():
    assert not matcher._same_usda_food(FOUNDATION_BELLY_SKIN, FNDDS_PORK_BELLY)
    assert not matcher._same_usda_food(SR_PORK_GROUND_RAW, FNDDS_PORK_GROUND)


def test_a_cooked_row_is_fnddss_row_as_eaten():
    assert matcher._same_usda_food(SR_PORK_GROUND_COOKED, FNDDS_PORK_GROUND)
    # "skin eaten" is how FNDDS says it, not another food.
    assert matcher._same_usda_food(SR_THIGH_STEWED_SKIN, FNDDS_THIGH_STEWED_SKIN)


def test_another_dataset_may_not_leave_out_the_cut():
    assert not matcher._same_usda_food(SR_THIGH_STEWED_SKIN, SR_CHICKEN_STEWED_SKIN)


def test_a_raw_line_never_borrows_from_a_cooked_fndds_row():
    assert matcher._names_other_variant("ground pork", FNDDS_PORK_GROUND)
    assert not matcher._names_other_variant("cooked ground pork", FNDDS_PORK_GROUND)
    assert not matcher._names_other_variant("ground beef", FNDDS_BEEF_GROUND_RAW)


def test_skin_conflicts():
    assert matcher._skin_conflicts(True, SR_THIGH_SKIN_RAW)
    assert not matcher._skin_conflicts(True, SR_THIGH_SKINLESS_RAW)
    assert matcher._skin_conflicts(False, SR_THIGH_SKINLESS_RAW)
    assert not matcher._skin_conflicts(None, SR_THIGH_SKIN_RAW)


def fallback(monkeypatch, food, foods, unit, search, tokens, searched=(), **kw):
    monkeypatch.setattr(matcher, "_search_usda_for_ingredient", lambda s: list(searched))
    monkeypatch.setattr(matcher, "_same_food_pool", lambda f, fs, qt: list(fs))
    return matcher._volume_unit_fallback(food, foods, unit, search, tokens, **kw)


def test_a_counted_skinless_thigh_is_the_raw_skinless_thigh(monkeypatch):
    out = fallback(monkeypatch, FOUNDATION_THIGH_SKINLESS,
                   [FOUNDATION_THIGH_SKINLESS, SR_THIGH_SKIN_RAW, SR_BREAST_SKINLESS_RAW],
                   "piece", "chicken thigh", ["chicken", "thigh"],
                   searched=[SR_THIGH_SKINLESS_RAW], cut="thigh", skinless=True)
    assert out["fdc_id"] == "173627"
    assert out["_count_from"] == "2646171"


def test_a_count_never_moves_to_a_row_without_the_lines_cut(monkeypatch):
    # The breast has a "piece"; the thigh line keeps its own row, unmeasured.
    out = fallback(monkeypatch, FOUNDATION_THIGH_SKINLESS,
                   [FOUNDATION_THIGH_SKINLESS, SR_BREAST_SKINLESS_RAW],
                   "piece", "chicken thigh", ["chicken", "thigh"], cut="thigh", skinless=True)
    assert out["fdc_id"] == "2646171"


def test_a_raw_count_never_moves_to_a_cooked_fndds_row(monkeypatch):
    out = fallback(monkeypatch, FOUNDATION_BELLY_SKIN, [FOUNDATION_BELLY_SKIN, FNDDS_PORK_BELLY],
                   "slice", "pork belly", ["pork", "belly"])
    assert out["fdc_id"] == "2727576"


def test_a_cooked_count_moves_to_the_fndds_row(monkeypatch):
    out = fallback(monkeypatch, FOUNDATION_BELLY_SKIN, [FOUNDATION_BELLY_SKIN, FNDDS_PORK_BELLY],
                   "slice", "cooked pork belly", ["cooked", "pork", "belly"])
    assert out["fdc_id"] == "2705901"


def test_a_cooked_cup_is_fnddss_cup(monkeypatch):
    out = fallback(monkeypatch, SR_PORK_GROUND_COOKED, [SR_PORK_GROUND_COOKED, FNDDS_PORK_GROUND],
                   "cup", "cooked ground pork", ["cooked", "ground", "pork"])
    assert out["fdc_id"] == "2705863"


def test_a_raw_cup_of_ground_meat_converts_by_the_raw_cup(monkeypatch):
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id",
                        lambda fdc: FNDDS_BEEF_GROUND_RAW if fdc == "2705853" else None)
    monkeypatch.setattr(matcher, "_density_relative",
                        lambda *a: pytest.fail("a raw meat cup takes no relative's cup"))
    out = fallback(monkeypatch, SR_PORK_GROUND_RAW, [SR_PORK_GROUND_RAW, FNDDS_PORK_GROUND],
                   "cup", "ground pork", ["ground", "pork"])
    # The raw ground pork stays; FNDDS's raw ground beef only converts.
    assert out["fdc_id"] == "167902"
    assert out["_density_from"] == "2705853"
    assert out["_g_per_ml"] == pytest.approx(225.0 / matcher._volume_to_ml(1.0, "cup"))


def test_a_raw_cup_of_other_meat_stays_unmeasured(monkeypatch):
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id", lambda fdc: None)
    out = fallback(monkeypatch, FOUNDATION_BELLY_SKIN, [FOUNDATION_BELLY_SKIN, FNDDS_PORK_BELLY],
                   "cup", "pork belly", ["pork", "belly"])
    assert out == FOUNDATION_BELLY_SKIN


def alias_row(tmp_path, monkeypatch, line, fitted):
    monkeypatch.setattr(matcher, "_alias_match", lambda *a: (FOUNDATION_BELLY_SKIN, None))
    monkeypatch.setattr(matcher, "match_ingredient", lambda *a, **k: (fitted, 0.95, "high", None))
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(["Test", line], name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    [row] = [r for r in matcher.build_output_rows(str(csv), [], 0.0) if r.get("_type") == "data"]
    return row


def test_the_alias_takes_the_row_its_count_moved_to(tmp_path, monkeypatch):
    moved = {**FNDDS_PORK_BELLY, "_count_from": "2727576"}
    row = alias_row(tmp_path, monkeypatch, "4 slice cooked pork belly", moved)
    assert str(row["food_id"]) == "2705901"
    assert row["unit_label"].startswith("1 slice")


def test_the_alias_keeps_its_food_against_any_other_row(tmp_path, monkeypatch):
    row = alias_row(tmp_path, monkeypatch, "4 slice cooked pork belly", FNDDS_PORK_BELLY)
    assert str(row["food_id"]) == "2727576"


@pytest.mark.parametrize("label", ["4 oz", "1 oz", "oz, boneless", "1 lb", "100 g", "1 ONZ", "85 GRM"])
def test_a_count_measured_by_a_weight_is_flagged(label):
    # "2 beef shank" went in as 2 oz and "1 milkfish" as 3 oz, unflagged.
    reason = matcher._unmeasured_reason({"label": label}, "piece", True, False, False, "Main")
    assert reason == f"no piece portion, measured by '{label}'"


@pytest.mark.parametrize("label", ["1 thigh with skin", "1 chop", "1 large/jumbo shrimp"])
def test_a_count_measured_by_a_piece_is_not_flagged(label):
    assert matcher._unmeasured_reason({"label": label}, "piece", True, False, False, "Main") == ""


def test_a_weight_line_measured_by_a_weight_is_not_flagged():
    assert matcher._unmeasured_reason({"label": "4 oz"}, "lb", False, False, False, "Main") == ""


def test_a_counted_line_on_a_weight_only_food_is_flagged(tmp_path, monkeypatch):
    shank = usda(14, 169441, *SR, "Beef, shank crosscuts, separable lean only, trimmed to 1/4\" fat, "
                 "choice, raw", "Beef shank crosscuts, lean only, 1/4\" fat, choice, raw", 128,
                 [("oz", 28.35), ("lb", 453.6)])
    monkeypatch.setattr(matcher, "match_ingredient", lambda *a, **k: (shank, 0.95, "high", None))
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(["Test", "2 beef shank"], name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    [row] = [r for r in matcher.build_output_rows(str(csv), [], 0.0) if r.get("_type") == "data"]
    assert row["_unmeasured"].startswith("no piece portion, measured by")
    assert row["notes"].startswith("CHECK AMOUNT")


FNDDS_THIGH_SIZES = usda(15, 2706037, *FNDDS, "Chicken thigh, stewed, skin eaten",
                         "Chicken thigh, stewed, skin eaten", 227,
                         [("cup, cooked, diced", 135.0), ("small thigh", 80.0), ("medium thigh", 90.0),
                          ("large thigh", 110.0), ("thigh", 90.0)])


@pytest.mark.parametrize("line, grams", [
    ("stewed skin-on chicken thigh", 90.0),   # unsaid: not the small one listed first
    ("small stewed skin-on chicken thigh", 80.0),
    ("large stewed skin-on chicken thigh", 110.0),
])
def test_a_counted_cut_takes_the_size_the_line_says_else_medium(line, grams):
    food = {**FNDDS_THIGH_SIZES, "_cut_keyword": "thigh"}
    assert matcher.pick_best_portion(food, "piece", None, 6.0, line)["gram_weight"] == grams
