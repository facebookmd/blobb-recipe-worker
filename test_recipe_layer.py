"""The recipe layer on the shared name search (26 Oct 2026, stage 2 of
unifying the app's food search and the matcher; recipe_matcher.
_match_ingredient_once).

Layer 1 (food_name_search, the app's search) ranks the foods; the recipe
layer re-ranks its best rows and never replaces them: boosts.json pins,
recipe words ("bone-in skin-on", "fresh", "cooked"), a raw food unless the
line is cooked, and among rows layer 1 ranks alike, the one with a portion
in the line's unit. The offline tests stub layer 1 and the portions; the
live ones search Supabase.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import pytest

import food_name_search as layer1
import parse_recipe as parser
import recipe_matcher as matcher


def row(i, description, display_name=None, data_type="SR Legacy", kcal=100.0, branded=False):
    return {"id": i, "fdc_id": i, "description": description,
            "display_name": display_name or description,
            "source_set": "branded" if branded else data_type.lower().replace(" ", "_"),
            "data_type": "Branded" if branded else data_type, "calories_100g": kcal}


@pytest.fixture
def shared(monkeypatch):
    """Layer 1 answers from *results* ({search text: rows}, ranked as layer 1
    ranks them); *portions* holds each row's portion labels."""
    results, portions, searched = {}, {}, []

    def search(text, limit=60):
        searched.append(text)
        split = layer1.split_portion_words(text)
        rows = results.get(split.food, [])
        return layer1.rank_rows(layer1.Query.parse(split.food), rows), split

    def load_portions(ids):
        return {i: [{"label": label, "grams": grams, "sequence_number": n}
                    for n, (label, grams) in enumerate(portions.get(i, [("1 cup", 100.0)]), 1)]
                for i in ids}

    monkeypatch.setattr(layer1, "search", search)
    monkeypatch.setattr(matcher, "load_portions_for_food_ids", load_portions)
    monkeypatch.setattr(matcher, "_respelled", lambda ingredient, *a, **k: ingredient)
    monkeypatch.setattr(matcher, "_MATCH_CACHE", {})
    return results, portions, searched


def match(line_ingredient, unit="", rules=(), is_cooked=False):
    return matcher.match_ingredient(line_ingredient, list(rules), 0.45, "", unit, is_cooked)[0]


def test_a_portion_in_the_lines_unit_decides_between_rows_ranked_alike(shared):
    results, portions, _ = shared
    # SR "Garlic, raw" has a clove; Foundation's has only 1 RACC.
    results["garlic"] = [row(1, "Garlic, raw", data_type="Foundation", kcal=143),
                         row(2, "Garlic, raw", kcal=149)]
    portions[1] = [("1 RACC", 3.0)]
    portions[2] = [("1 clove", 3.0), ("1 cup", 136.0)]
    assert match("garlic", "clove")["fdc_id"] == "2"


def test_the_unit_never_overrides_layer_1s_order(shared):
    results, portions, _ = shared
    results["egg"] = [row(1, "Egg, whole, raw", data_type="Survey (FNDDS)", kcal=143),
                      row(2, "Egg, white only, raw", data_type="Survey (FNDDS)", kcal=52)]
    portions[1] = [("1 cup", 243.0)]
    portions[2] = [("1 large", 33.0)]
    assert match("egg")["fdc_id"] == "1"


def test_a_recipe_food_is_raw_unless_the_line_is_cooked(shared):
    results, _, _ = shared
    results["quinoa"] = [row(1, "Quinoa, cooked", kcal=120), row(2, "Quinoa, uncooked", kcal=368)]
    assert match("quinoa", "cup")["fdc_id"] == "2"
    assert match("quinoa", "cup", is_cooked=True)["fdc_id"] == "1"


def test_bone_in_skin_on_keeps_the_skin(shared):
    results, _, searched = shared
    results["chicken thigh"] = [
        row(1, "Chicken, thigh, boneless, skinless, raw", "Chicken thigh, boneless, skinless, raw",
            data_type="Foundation", kcal=149),
        row(2, "Chicken, broilers or fryers, thigh, meat and skin, raw", "Chicken thigh, with skin, raw",
            kcal=221)]
    results["boneless skinless chicken thigh"] = results["chicken thigh"]
    food = match("bone-in skin-on chicken thigh")
    assert food["fdc_id"] == "2"
    assert food["_cut_keyword"] == "thigh"
    assert searched[-1].split() == ["chicken", "thigh"]
    assert match("boneless skinless chicken thigh")["fdc_id"] == "1"


def test_a_state_word_no_row_carries_is_searched_without(shared):
    results, _, searched = shared
    results["fresh ginger"] = [row(1, "FRESH ORGANIC VINAIGRETTE, TOASTED SESAME GINGER", branded=True)]
    results["ginger"] = [row(2, "Ginger root, raw", kcal=80)]
    assert match("fresh ginger")["fdc_id"] == "2"
    assert searched == ["fresh ginger", "ginger"]


def test_cooked_pasta_is_the_dry_product_by_weight(shared):
    results, _, _ = shared
    fresh = row(1, "LINGUINE", branded=True, kcal=282)
    fresh.update(serving_size=85, serving_size_unit="g", household_serving_full_text="1 1/4 cup")
    dry = [row(i, "LINGUINE", branded=True, kcal=357) for i in (2, 3)]
    for r in dry:
        r.update(serving_size=56, serving_size_unit="g", household_serving_full_text="2 oz")
    results["cooked linguine"] = [row(4, "SEAFOOD LINGUINE", branded=True, kcal=121)]
    results["linguine"] = [fresh, *dry]
    assert match("cooked linguine", "cup")["energy_kcal"] == 357


def test_a_recipe_meat_is_lean_and_fat(shared):
    results, _, _ = shared
    rows = [row(1, "Beef, brisket, whole, separable lean only, trimmed to 1/8\" fat, all grades, raw",
                "Beef brisket, whole, lean only, raw", kcal=157),
            row(2, "Beef, brisket, whole, separable lean and fat, trimmed to 1/8\" fat, all grades, raw",
                "Beef brisket, whole, 1/8\" fat, raw", kcal=253)]
    results["beef brisket"] = rows
    assert match("beef brisket", "lb")["fdc_id"] == "2"


def test_fndds_from_canned_is_a_cooked_dish(shared):
    results, _, _ = shared
    results["canned kidney beans"] = [
        row(1, "Kidney beans, from canned, no added fat", data_type="Survey (FNDDS)", kcal=135),
        row(2, "Beans, kidney, all types, mature seeds, canned", "Kidney beans, all types, canned", kcal=84)]
    assert match("canned kidney beans", "cup")["fdc_id"] == "2"


def test_cooked_pasta_skips_a_pasta_meal(shared):
    results, _, _ = shared
    meal = row(1, "ZITI", branded=True, kcal=235)
    dry = row(2, "ZITI, ENRICHED MACARONI PRODUCT", branded=True, kcal=357)
    results["cooked ziti"] = [meal, dry]
    assert match("cooked ziti", "cup")["energy_kcal"] == 357


def test_ear_is_a_unit():
    row_ = parser.parse_ingredient_line("2 ears sweet corn")
    assert (row_["qty"], row_["unit"], row_["ingredient"]) == ("2.0", "ear", "sweet corn")


def test_a_boost_pin_wins_when_its_food_fits_the_preparation(shared, monkeypatch):
    results, _, _ = shared
    pinned = matcher._build_supabase_usda_food(row(9, "Roasting chicken, with skin, raw"), 0, {})
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id", lambda fdc_id: pinned if fdc_id == "9" else None)
    rules = [{"trigger": "whole chicken", "fdc_id": "9", "weight": 0.95}]
    assert match("chicken", "whole", rules)["fdc_id"] == "9"
    # "fried" isn't a roasting chicken: layer 1 names it.
    results["fried whole chicken"] = [row(3, "Fried chicken, whole", data_type="Survey (FNDDS)")]
    assert match("fried whole chicken", "", rules)["fdc_id"] == "3"


LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_ANON_KEY"),
                          reason="needs SUPABASE_ANON_KEY (live Supabase)")


# Lines the shared search got wrong with no recipe layer (stage 1), and the
# food the old matcher gave them too; then lines the old matcher's shortcuts
# covered (stage 3, 27 Oct 2026).
@LIVE
@pytest.mark.parametrize("line,expected", [
    ("3 cloves garlic", "Garlic, raw"),
    ("2 lb bone-in skin-on chicken thighs", "Chicken thigh, with skin, raw"),
    ("1 whole chicken", "Roasting chicken, with skin, giblets, and neck, raw"),
    ("1 tsp smoked paprika", "SMOKED PAPRIKA"),
    ("2 star anise", "ANISE STAR"),  # its boosts.json rewrite, as the matcher
    ("1 cup frozen peas", "Green peas, frozen, unprepared"),
    ("1 tbsp fresh ginger, grated", "Ginger root, raw"),
    ("2 tbsp vegetable oil", "Soybean oil, salad or cooking"),
    # 27 Oct 2026 pins and rules.
    ("5 anchovy fillets", "European anchovy, canned in oil, drained"),
    ("3 oz unsweetened baking chocolate", "Unsweetened baking chocolate squares"),
    ("2 cup crushed ice", "Tap water, drinking"),
    ("2.5 cup canned kidney beans", "Kidney beans, all types, canned"),
    ("1 cup cooked ziti", "ZITI, ENRICHED MACARONI PRODUCT"),
    ("2 ear sweet corn", "White sweet corn, raw"),
    ("1 cup fresh diced tomatoes", "Tomatoes, raw"),
    ("2 red chili", "Red hot chili peppers, raw"),
    ("1 cup grilled chicken", "Chicken fillet, grilled"),
    ("1 lb fried chicken", "Chicken, skinless, fried"),
    ("2 eggs, scrambled", "Egg, whole, raw"),
    ("1 lb boneless skinless chicken pieces", "Roasting chicken, skinless, raw"),
    ("1 cup cut yardlong beans", "Yardlong bean, raw"),
    # The food_aliases row from supabase-usda 20261027140000.
    pytest.param("3 cup green papaya chunks", "Papayas, raw", marks=pytest.mark.skipif(
        os.environ.get("SUPABASE_ANON_KEY") and "green papaya" not in layer1._food_aliases(),
        reason="green papaya alias not pushed yet")),
])
def test_recipe_lines(line, expected, monkeypatch):
    monkeypatch.setattr(matcher, "_MATCH_CACHE", {})
    row_ = parser.parse_ingredient_line(line)
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    food = matcher.match_ingredient(row_["ingredient"], rules, 0.45, "American",
                                    row_["unit"], row_["is_cooked"])[0]
    assert food is not None and food["display_name"] == expected


# ── Bone-in cuts (27 Oct 2026) ──────────────────────────────────────────────
# USDA's portion weights are edible already (SR28 documentation: "a chicken
# leg without the bone"): a count takes no share. A recipe's own weight as
# bought does (parse_recipe.as_bought), by the USDA food it matched.

def sr(desc):
    return {"source": "usda", "raw_description": desc}


CHICKEN_THIGH = sr("Chicken, broilers or fryers, thigh, meat and skin, raw")


@pytest.mark.parametrize("line, desc, share", [
    ("1 lb bone-in skin-on chicken thigh", CHICKEN_THIGH["raw_description"], 0.83),  # SR 05094
    ("1 lb chicken leg quarters", "Chicken, broilers or fryers, leg, meat and skin, raw", 0.73),
    ("2 lb chicken wings", "Chicken, broilers or fryers, wing, meat and skin, raw", 0.62),
    ("1 lb bone-in beef shank",
     "Beef, shank crosscuts, separable lean only, trimmed to 1/4\" fat, choice, raw", 0.60),
    ("2 lb veal shank", "Veal, shank, separable lean and fat, raw", 0.51),
    ("2 lb veal shank", "Veal, shank (fore and hind), separable lean and fat, raw", 0.71),
    ("2 lb pork baby back ribs", "Pork, fresh, backribs, separable lean and fat, raw", 0.63),
    ("4 lb whole chicken", "Chicken, broilers or fryers, meat and skin and giblets and neck, raw", 0.69),
    # Bone share of the raw weight, and the matcher's yield for the cooked row.
    ("3 lb bone-in pork shoulder",
     "Pork, fresh, shoulder, (Boston butt), blade (steaks), separable lean and fat, cooked, braised", 0.76),
])
def test_a_weight_bought_with_bone_counts_its_food_s_edible_share(line, desc, share):
    parsed = parser.parse_ingredient_line(line)
    got = matcher._edible_share(sr(desc), parsed["as_bought"])
    assert got is not None and got[0] == pytest.approx(share)


@pytest.mark.parametrize("line, desc", [
    # Another animal's cut: no share borrowed from beef, chicken or pork.
    ("2 lb lamb shanks", "Lamb, domestic, foreshank, separable lean and fat, raw"),
    ("2 lb turkey wings", "Turkey, wing, meat and skin, raw"),
    ("2 lb beef back ribs", "Beef, rib, back ribs, bone-in, separable lean and fat, raw"),
    # Named after a cut, not the cut.
    ("4 oz buffalo wing sauce", "Sauce, hot chile, sriracha"),
])
def test_no_share_from_another_food(line, desc):
    parsed = parser.parse_ingredient_line(line)
    assert matcher._edible_share(sr(desc), parsed["as_bought"]) is None


def test_a_sauce_named_after_a_cut_is_not_bought_with_bone():
    assert parser.parse_ingredient_line("4 oz buffalo wing sauce")["as_bought"] == ""


@pytest.mark.parametrize("line", [
    "2 bone-in skin-on chicken thigh",   # a count: USDA's "1 thigh" has no bone
    "4 oz boneless chicken thigh",
    "4 oz chicken thigh",                # a thigh is bone-in only when it says so
])
def test_counts_and_boneless_weights_take_no_share(line):
    parsed = parser.parse_ingredient_line(line)
    assert matcher._edible_share(CHICKEN_THIGH, parsed["as_bought"]) is None


def test_a_branded_label_takes_no_share():
    branded = {**CHICKEN_THIGH, "source": "branded"}
    assert matcher._edible_share(branded, "bone-in") is None


def test_a_100_g_label_serving_that_names_a_measure_is_kept():
    # YOUNG THAI COCONUT MEAT's label: 0.5 cup = 100 g. It was taken for the
    # per-100 g basis and dropped (27 Oct 2026).
    row = {"serving_size": 100, "serving_size_unit": "g", "household_serving_full_text": "0.5 cup"}
    assert matcher._branded_label_serving(row, "2288946")["label"] == "0.5 cup"
    assert matcher._branded_label_serving({**row, "household_serving_full_text": "100 GRM"}, "1") is None
    assert matcher._branded_label_serving({**row, "household_serving_full_text": ""}, "1") is None
