"""Units sent to the app carry no count in their label.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import app as worker
from parse_recipe import parse_ingredient_line


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("4 oz", (4.0, "oz")),
        ("1 cup", (1.0, "cup")),
        ("0.5 cup", (0.5, "cup")),
        ("1/2 cup", (0.5, "cup")),
        ("6 slices", (6.0, "slices")),
        ("100 g", (100.0, "g")),
        ("1 cup, chopped", (1.0, "cup, chopped")),
        ("medium", (1.0, "medium")),
        ("serving", (1.0, "serving")),
        ("0 cup", (1.0, "0 cup")),
    ],
)
def test_split_count(label, expected):
    assert worker._split_count(label) == expected


def unit(label, kcal, grams):
    return {"label": label, "caloriesPerUnit": kcal, "gramsPerUnit": grams}


def test_each_unit_becomes_one_of_its_kind():
    units, default, factor = worker._per_single_unit(
        [unit("4 oz", 200.0, 113.0), unit("6 slices", 300.0, 170.0)],
        default_index=0,
    )
    assert [u["label"] for u in units] == ["oz", "slices"]
    assert units[0]["caloriesPerUnit"] == 50.0
    assert units[0]["gramsPerUnit"] == 28.25
    assert units[1]["caloriesPerUnit"] == 50.0
    assert default == 0
    assert factor == 4.0


def test_the_component_total_is_unchanged():
    # "2 · 4 oz" (400 kcal) becomes "8 · oz".
    original = [unit("4 oz", 200.0, 113.0)]
    units, default, factor = worker._per_single_unit(original, default_index=0)
    assert 2 * factor == 8
    assert units[default]["caloriesPerUnit"] * 2 * factor == pytest.approx(400.0)


def test_units_that_collapse_to_one_label_keep_the_first():
    units, default, factor = worker._per_single_unit(
        [unit("1 cup", 100.0, 240.0), unit("0.5 cup", 50.0, 120.0), unit("1 tbsp", 6.0, 15.0)],
        default_index=1,
    )
    assert [u["label"] for u in units] == ["cup", "tbsp"]
    assert default == 0
    assert factor == 0.5


def test_a_unit_without_grams_keeps_none():
    units, _, _ = worker._per_single_unit([unit("2 pieces", 80.0, None)], default_index=0)
    assert units[0] == {"label": "pieces", "caloriesPerUnit": 40.0, "gramsPerUnit": None}


@pytest.mark.parametrize(
    ("qty", "expected"),
    [
        (8.028, 8.0),
        (2.0, 2.0),
        (0.497, 0.5),
        (0.49, 0.49),
        (0.334, 0.3333),
        (2.66, 2.6667),
        (1.3, 1.3),
        (0.0, 0.0),
    ],
)
def test_wheel_amount(qty, expected):
    assert worker._wheel_amount(qty) == expected


def test_a_pinned_food_is_found_in_the_fetch_cache(monkeypatch):
    # Boost-pinned foods are fetched by ID, not searched; without them the
    # component got only its chosen unit (gochujang: tbsp, no g).
    food = {"fdc_id": "B_2171715", "portions": []}
    monkeypatch.setattr(worker.matcher, "_INGREDIENT_INDEX_CACHE", {})
    monkeypatch.setattr(worker.matcher, "_FDC_FETCH_CACHE", {"B_2171715": food})
    assert worker._find_food("B_2171715") is food
    assert worker._find_food("B_1") is None


# ── Count words before the food, and leaves that are the food ─────────────

@pytest.mark.parametrize("line, qty, unit, ingredient", [
    ("1 fillet salmon", "1.0", "fillet", "salmon"),
    ("2 salmon fillets", "2.0", "fillet", "salmon"),
    ("4 leaf basil", "4.0", "leaf", "basil"),          # was dropped
    ("4 leaves of basil", "4.0", "leaf", "basil"),
    ("2 sprigs thyme", "2.0", "sprig", "thyme"),        # was dropped
    ("0.25 cup cilantro leaves", "0.25", "cup", "cilantro"),
    ("1 tbsp chopped basil leaves", "1.0", "tbsp", "basil"),
    # Leaves that are a food of their own keep the word (they matched beef
    # curry, limes and bananas).
    ("10 curry leaves", "10.0", "piece", "curry leaves"),
    ("4 kaffir lime leaves", "4.0", "piece", "kaffir lime leaves"),
    ("1 banana leaf", "1.0", "piece", "banana leaf"),
    ("2 bay leaves", "2.0", "piece", "bay leaves"),
    ("2 tbsp flat-leaf parsley", "2.0", "tbsp", "flat-leaf parsley"),
    ("0.5 cup bamboo shoots", "0.5", "cup", "bamboo shoots"),
    ("1 cup broccoli florets", "1.0", "cup", "broccoli"),
])
def test_count_words_and_leaves(line, qty, unit, ingredient):
    r = parse_ingredient_line(line)
    assert (r["qty"], r["unit"], r["ingredient"]) == (qty, unit, ingredient)


# ── Aromatic leaves: note rows, no calories ───────────────────────────────

@pytest.mark.parametrize("line, note", [
    ("10 curry leaves", True), ("4 kaffir lime leaves", True),
    ("3 makrut lime leaves", True), ("2 pandan leaves", True),
    ("1 banana leaf", True), ("2 lime leaves", True),
    ("2 bay leaves", False), ("1 tbsp lime juice", False),
    ("1 banana", False), ("1 cup curry sauce", False),
])
def test_aromatic_leaves_are_notes(tmp_path, monkeypatch, line, note):
    import parse_recipe
    import recipe_matcher as matcher

    monkeypatch.setattr(matcher, "match_ingredient", lambda *a, **k: (None, 0.0, "none", None))
    monkeypatch.setattr(matcher, "_search_and_build_index", lambda *a, **k: None)
    meta, ings = parse_recipe.parse_single_block(["Test", line], name_hint="recipe")
    csv = tmp_path / "r.csv"
    parse_recipe.write_recipes_csv([(meta, ings)], str(csv), append=False)
    [row] = [r for r in matcher.build_output_rows(str(csv), [], 0.0)
             if r.get("_type") in ("data", "note")]
    assert (row["_type"] == "note") is note
