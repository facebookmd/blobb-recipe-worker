"""Systemic matching errors found in the Italian dry run (22 Oct 2026).

Restaurant and fast-food dishes competed as ingredients, ties went to the
first row Supabase returned, prep words that name a product were dropped,
"Italian" was dropped from "Italian sausage", the volume fallback switched
foods, "1 cup, whipped" measured cups of cream, counts fell back to "1 can",
and boost triggers matched inside other words.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import food_name_search as layer1
import parse_recipe as parser
import recipe_matcher as matcher


def usda(fdc_id, name, desc=None, category="Dairy and Egg Products",
         data_type="SR Legacy", kcal=100.0, portions=(), raw=False):
    return {
        "source": "usda", "fdc_id": str(fdc_id), "display_name": name,
        "raw_description": desc or name, "alt_names": [], "category": category,
        "data_type": data_type, "energy_kcal": kcal, "is_raw": raw,
        "portions": [{"portion_id": f"{fdc_id}-{i}", "label": label, "gram_weight": grams,
                      "gram_col": "", "portion_idx": i}
                     for i, (label, grams) in enumerate(portions, start=1)],
    }


from recipe_layer_stub import best  # the recipe layer on just these foods


# ── 1. Source filter ────────────────────────────────────────────────────────

STICKS = usda(169011, "Mozzarella sticks, Applebee's", category="Restaurant Foods",
              portions=[("1 piece", 32.0)])
MOZZARELLA = usda(170845, "Mozzarella cheese, whole milk", "Cheese, mozzarella, whole milk",
                  portions=[("1 oz", 28.35)])
PIZZA = usda(173295, 'Pepperoni pizza, 14"', category="Fast Foods", portions=[("1 slice", 111.0)])
PEPPERONI = usda(174575, "Pepperoni, beef and pork, sliced",
                 category="Sausages and Luncheon Meats", portions=[("1 oz", 28.0)])


def test_restaurant_dishes_are_not_ingredients():
    assert best("mozzarella", [STICKS, MOZZARELLA], "oz") is MOZZARELLA
    assert best("pepperoni", [PIZZA, PEPPERONI], "oz") is PEPPERONI


def test_a_line_naming_the_dish_still_finds_it():
    assert best("pepperoni pizza", [PIZZA, PEPPERONI], "slice") is PIZZA


# ── 2. Ties ─────────────────────────────────────────────────────────────────

def test_a_tie_goes_to_the_reference_row_over_fndds():
    fndds = usda(2709786, "Garlic, raw", category="Garlic", data_type="Survey (FNDDS)",
                 portions=[("1 clove", 3.0)], raw=True)
    legacy = usda(169230, "Garlic, raw", category="Vegetables and Vegetable Products",
                  portions=[("1 clove", 3.0)], raw=True)
    assert best("garlic", [fndds, legacy], "clove") is legacy


def test_a_tie_goes_to_the_row_with_fewer_unsaid_words():
    mix = usda(170020, "Peas and onions, frozen, unprepared",
               category="Vegetables and Vegetable Products", portions=[("0.5 cup", 69.0)], raw=True)
    peas = usda(170016, "Green peas, frozen, unprepared",
                "Peas, green, frozen, unprepared (Includes foods for USDA's Food Distribution Program)",
                category="Vegetables and Vegetable Products", portions=[("1 cup", 134.0)], raw=True)
    assert best("frozen peas", [mix, peas], "cup") is peas


def test_a_boost_capped_at_one_still_ranks_the_closer_row():
    ready = usda(171538, "Beef broth or bouillon, canned, ready-to-serve",
                 category="Soups, Sauces, and Gravies", portions=[("1 cup", 240.0)])
    condensed = usda(171548, "Beef broth, bouillon, and consommé, canned, condensed",
                     category="Soups, Sauces, and Gravies", portions=[("0.5 cup", 124.0)])
    assert best("beef broth canned", [condensed, ready], "cup") is ready


def test_a_label_error_over_nine_kcal_a_gram_is_skipped():
    bad = {"source": "branded", "fdc_id": "B_2278440", "display_name": "JAPANESE STYLE MAYONNAISE",
           "item_name": "JAPANESE STYLE MAYONNAISE", "alt_names": [], "energy_kcal": 2000.0,
           "portions": [{"portion_id": "x", "label": "1 tbsp", "gram_weight": 5.0, "portion_idx": 1}]}
    assert best("japanese mayonnaise", [bad]) is None


# ── 3. Prep words that name the product ─────────────────────────────────────

def test_a_form_word_the_food_names_scores_it_higher():
    soup = usda(2709759, "Soup, tomato, canned", category="Soups", data_type="Survey (FNDDS)",
                portions=[("1 cup", 245.0)])
    diced = usda(333281, "Diced ripe red tomatoes, canned", category="Vegetables and Vegetable Products",
                 data_type="Foundation", portions=[("1 cup", 245.0)])
    assert best("canned diced tomatoes", [soup, diced], "cup") is diced


@pytest.mark.parametrize("line, name", [
    ("1/3 cup grated parmesan", "grated parmesan"),
    ("1.75 cup canned diced tomatoes", "canned diced tomatoes"),
    ("3/4 cup frozen peas", "frozen peas"),
    ("1 tsp dried oregano", "dried oregano"),
    ("2 cup shredded mozzarella", "shredded mozzarella"),
    ("1 cup finely chopped onion", "onion"),
])
def test_the_parser_keeps_product_forms(line, name):
    assert parser.parse_ingredient_line(line)["ingredient"] == name


def test_a_kept_form_word_is_dropped_when_nothing_matches(monkeypatch):
    calls = []

    def once(ingredient, *args, **kwargs):
        calls.append(ingredient)
        return ({"fdc_id": "1"}, 1.0, "high", None) if ingredient == "mung beans" else (None, 0.0, "none", None)

    monkeypatch.setattr(matcher, "_match_ingredient_once", once)
    monkeypatch.setattr(matcher, "_respelled", lambda ingredient, *a, **k: ingredient)
    assert matcher.match_ingredient("dried mung beans", [])[0] == {"fdc_id": "1"}
    assert calls == ["dried mung beans", "mung beans"]


# ── 4. Cuisine words ────────────────────────────────────────────────────────

@pytest.mark.parametrize("line, name", [
    ("1 lb Italian sausage", "Italian sausage"),
    ("1 tsp Italian seasoning", "Italian seasoning"),
    ("1 tbsp Japanese mayonnaise", "Japanese mayonnaise"),
])
def test_the_parser_keeps_a_cuisine_word(line, name):
    assert parser.parse_ingredient_line(line)["ingredient"] == name


# ── 5. Volume from a sibling, not a different food ──────────────────────────

HEAVY = usda(2346386, "Heavy cream", "Cream, heavy", data_type="Foundation", kcal=340.0,
             portions=[("1 RACC", 15.0)])
WHIPPING = usda(170859, "Heavy whipping cream", "Cream, fluid, heavy whipping", kcal=340.0,
                portions=[("1 cup, whipped", 120.0), ("1 cup, fluid (yields 2 cups whipped)", 238.0),
                          ("1 tbsp", 15.0)])


def test_the_volume_fallback_keeps_the_food():
    food = matcher._volume_unit_fallback(HEAVY, [HEAVY, WHIPPING], "cup", "heavy cream",
                                         ["heavy", "cream"])
    assert food["fdc_id"] == HEAVY["fdc_id"]
    assert food["_density_from"] == WHIPPING["fdc_id"]
    # Its density only ("1 cup, fluid", 238 g); the portions stay its own.
    assert food["_g_per_ml"] == pytest.approx(238.0 / matcher._volume_to_ml(1.0, "cup"))
    assert food["portions"] == HEAVY["portions"]
    assert HEAVY["portions"] == [{"portion_id": "2346386-1", "label": "1 RACC", "gram_weight": 15.0,
                                  "gram_col": "", "portion_idx": 1}]


def test_a_relative_in_the_same_category_measures_a_racc_only_food(monkeypatch):
    baby = usda(1999632, "Spinach, baby", data_type="Foundation",
                category="Vegetables and Vegetable Products", portions=[("1 RACC", 85.0)])
    raw = usda(168462, "Spinach, raw", category="Vegetables and Vegetable Products",
               portions=[("1 cup", 30.0)], raw=True)
    souffle = usda(170494, "Spinach souffle", category="Vegetables and Vegetable Products",
                   portions=[("1 cup", 136.0)])
    monkeypatch.setattr(matcher, "_search_usda_for_ingredient", lambda q: [souffle, raw])
    food = matcher._volume_unit_fallback(baby, [baby], "cup", "baby spinach",
                                         ["baby", "spinach"])
    assert food["_density_from"] == raw["fdc_id"]
    assert food["_g_per_ml"] == pytest.approx(30.0 / matcher._volume_to_ml(1.0, "cup"))


def test_a_cup_weighing_100_g_is_a_real_cup():
    beans = usda(2709769, "Green beans, raw", portions=[("1 cup", 100.0), ("1 bean", 6.0)])
    assert matcher._has_compatible_volumetric_serving(beans, "cup")
    assert matcher._is_basis_portion({"label": "100g", "gram_weight": 100.0, "portion_idx": 0})
    assert not matcher._is_basis_portion({"label": "1 cup", "gram_weight": 100.0, "portion_idx": 1})


# ── 6. Portions ─────────────────────────────────────────────────────────────

def test_a_cup_of_cream_is_not_a_cup_of_whipped_cream():
    portion = matcher.pick_best_portion(WHIPPING, "cup", None, 1.0, "heavy cream")
    assert portion["gram_weight"] == 238.0
    whipped = matcher.pick_best_portion(WHIPPING, "cup", None, 1.0, "whipped cream")
    assert whipped["gram_weight"] == 120.0


def test_a_count_with_no_unit_portion_counts_the_food_itself():
    anchovy = usda(2706232, "Fish, anchovy", category="Fish", data_type="Survey (FNDDS)",
                   portions=[("1 can", 45.0), ("1 anchovy", 4.0)])
    assert matcher.pick_best_portion(anchovy, "fillet", None, 5.0, "anchovy")["label"] == "1 anchovy"


def test_a_regular_one_is_a_medium_one():
    cucumber = usda(2709784, "Cucumber, raw", data_type="Survey (FNDDS)",
                    portions=[("1 piece/slice", 10.0), ("1 regular", 200.0)])
    assert matcher.pick_best_portion(cucumber, "piece", None, 1.0, "cucumber medium")["label"] == "1 regular"


@pytest.mark.parametrize("label, unit, flagged", [
    ("1 tsp", "leaf", True),
    ("1 can", "fillet", True),
    ("1 RACC", "piece", True),
    ("1 anchovy", "fillet", False),
    ("4 oz", "piece", False),
    ("1 cup", "cup", False),
])
def test_a_count_measured_by_something_else_is_flagged(label, unit, flagged):
    countable = unit not in matcher.VOLUMETRIC_UNITS
    reason = matcher._unmeasured_reason({"label": label, "gram_weight": 1.0}, unit, countable,
                                        False, False, "Main")
    assert bool(reason) is flagged


def test_estimates_and_volume_mismatches_are_flagged():
    portion = {"label": "1 tbsp", "gram_weight": 14.8}
    assert matcher._unmeasured_reason(portion, "cup", False, True, False, "Main")
    assert matcher._unmeasured_reason(portion, "cup", False, False, True, "Main")
    assert not matcher._unmeasured_reason(portion, "tbsp", False, False, True,
                                          matcher.ABSORBED_OIL_SECTION)


def test_a_baby_variant_loses_to_the_plain_vegetable():
    baby = usda(168565, "Baby zucchini, raw", "Squash, zucchini, baby, raw",
                category="Vegetables and Vegetable Products", portions=[("1 medium", 11.0)], raw=True)
    plain = usda(169291, "Zucchini, includes skin, raw", "Squash, summer, zucchini, includes skin, raw",
                 category="Vegetables and Vegetable Products", portions=[("1 medium", 196.0)], raw=True)
    assert best("zucchini", [baby, plain], "piece") is plain


def test_squid_heads_its_mollusk_row():
    squid = usda(174223, "Squid, mixed species, raw", "Mollusks, squid, mixed species, raw",
                 category="Finfish and Shellfish Products", portions=[("3 oz", 85.0)], raw=True)
    assert layer1.usda_row_head_qualifiers(layer1.Query.parse("squid"), squid["raw_description"],
                                           squid["display_name"]) == ["mixed species", "raw"]
    assert best("squid", [squid]) is squid


# ── 7. Boost triggers ───────────────────────────────────────────────────────

@pytest.mark.parametrize("ingredient, trigger, fires", [
    ("eggplant", "egg", False),
    ("annatto powder", "natto", False),
    ("unsalted butter", "salt", False),
    ("eggs", "egg", True),
    ("tofu, silken", "silken tofu", True),
    ("gyoza wrapper", "gyoza wrappers", False),
])
def test_triggers_match_whole_words(ingredient, trigger, fires):
    assert matcher._boost_trigger_matches(ingredient, trigger) is fires


def test_a_one_word_trigger_does_not_rename_the_food_after_it(monkeypatch):
    monkeypatch.setattr(matcher, "_fetch_food_by_fdc_id", lambda fdc_id: {
        "170028": {"display_name": "White potatoes, flesh and skin, raw",
                   "raw_description": "Potatoes, white, flesh and skin, raw"},
        "170489": {"display_name": "Winter squash, all varieties, raw",
                   "raw_description": "Squash, winter, all varieties, raw"},
    }.get(fdc_id))
    potato = {"trigger": "potato", "boost": "potatoes flesh and skin raw", "fdc_id": "170028"}
    kabocha = {"trigger": "kabocha", "fdc_id": "170489", "weight": 0.95}
    garlic = {"trigger": "garlic", "boost": "garlic raw", "weight": 0.6}
    assert matcher.apply_boosts("potato gnocchi", [potato]) == ("potato gnocchi", 0.0, None)
    assert matcher.apply_boosts("garlic fried rice", [garlic]) == ("garlic fried rice", 0.0, None)
    assert matcher.apply_boosts("garlic cloves", [garlic])[0] == "garlic raw"
    assert matcher.apply_boosts("kabocha squash", [kabocha])[2] == "170489"


def test_a_boost_keeps_the_colour_the_line_says():
    rule = {"trigger": "bell pepper", "boost": "sweet red pepper raw", "weight": 0.6}
    assert matcher.apply_boosts("yellow bell pepper", [rule])[0] == "sweet yellow pepper raw"
    assert matcher.apply_boosts("bell pepper", [rule])[0] == "sweet red pepper raw"


# ── Spellings one letter off (23 Oct 2026) ──────────────────────────────────

CRIMINI = {"display_name": "Mushrooms, brown, italian, or crimini, raw",
           "description": "Mushrooms, brown, italian, or crimini, raw"}


@pytest.fixture
def spelling(monkeypatch):
    """USDA search returns [usda]; the spelling search returns rows[word]."""
    state = {"usda": [], "rows": {}, "asked": []}
    monkeypatch.setattr(matcher, "_search_usda_for_ingredient", lambda q: state["usda"])

    def by_spelling(word, limit=40):
        state["asked"].append(word)
        return state["rows"].get(word, [])

    monkeypatch.setattr(matcher, "supabase_search_food_names_by_spelling", by_spelling)
    return state


def test_a_word_usda_lacks_takes_its_one_letter_off_spelling(spelling):
    spelling["rows"]["cremini"] = [CRIMINI]
    assert matcher._respelled("cremini mushrooms", []) == "crimini mushrooms"


def test_a_missing_letter_is_put_back(spelling):
    spelling["rows"]["mozarella"] = [{"display_name": "Mozzarella cheese, whole milk",
                                      "description": "Cheese, mozzarella, whole milk"}]
    assert matcher._respelled("fresh mozarella", []) == "fresh mozzarella"


def test_short_words_are_never_respelled(spelling):
    spelling["rows"]["beer"] = [{"display_name": "Beef, ground", "description": "Beef, ground"}]
    assert matcher._respelled("beer", []) == "beer"
    assert spelling["asked"] == []


def test_a_word_usda_has_is_left_alone(spelling):
    spelling["usda"] = [{"display_name": "Cremini mushrooms", "raw_description": ""}]
    spelling["rows"]["cremini"] = [CRIMINI]
    assert matcher._respelled("cremini mushrooms", []) == "cremini mushrooms"
    assert "cremini" not in spelling["asked"]


def test_two_letters_off_is_not_a_typo(spelling):
    spelling["rows"]["mozarela"] = [{"display_name": "Mozzarella cheese", "description": ""}]
    assert matcher._respelled("mozarela", []) == "mozarela"


def test_a_boost_rule_keeps_the_line_as_written(spelling):
    spelling["rows"]["kalamansi"] = [{"display_name": "Calamansi juice", "description": ""}]
    rule = {"trigger": "kalamansi", "fdc_id": "B_1", "weight": 0.95}
    assert matcher._respelled("kalamansi", [rule]) == "kalamansi"
    assert spelling["asked"] == []


def test_no_spelling_function_yet_means_no_change(monkeypatch):
    import supabase_food_source as source

    def missing(url):
        raise RuntimeError("Supabase request failed (404) for x: PGRST202")

    monkeypatch.setattr(source, "_request_json", missing)
    monkeypatch.setattr(source, "_SPELLING_MISSING", False)
    monkeypatch.setattr(source, "_SPELLING_CACHE", {})
    monkeypatch.setattr(source, "is_configured", lambda: True)
    assert source.search_food_names_by_spelling("cremini") == []
    assert source._SPELLING_MISSING


def test_the_new_spelling_comes_with_the_lines_other_words(spelling):
    spelling["rows"]["glass"] = [{"display_name": "Wheat grass, raw", "description": ""},
                                 {"display_name": "Noodles, egg", "description": ""}]
    assert matcher._respelled("glass noodles", []) == "glass noodles"
