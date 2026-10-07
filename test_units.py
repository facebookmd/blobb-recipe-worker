"""Units sent to the app carry no count in their label.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

import app as worker


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
