"""The calorie check after each matcher run (13 Nov 2026): templates more
than 13% (20% until 25 Nov 2026) and 30 kcal from their outside reference, and new templates with
no reference, are listed; references that can't be compared are skipped.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import csv
import json

import check_template_calories as check


def write_output(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["template_id", "template_name", "cal_tot"])
        w.writeheader()
        for tid, name, kcal in rows:
            w.writerow({"template_id": tid, "template_name": name, "cal_tot": kcal})


def test_calories_per_serving_add_up_by_template(tmp_path):
    out = tmp_path / "out.csv"
    write_output(out, [("adobo", "Adobo", 400), ("adobo", "Adobo", 60.4), ("salad", "Salad", 27),
                       ("", "", "")])
    got = check.template_calories(str(out))
    assert list(got) == ["adobo", "salad"]
    assert got["adobo"]["kcal"] == 460.4


def test_off_needs_both_the_share_and_the_calories():
    templates = {"stew": {"name": "Stew", "kcal": 700}, "salad": {"name": "Salad", "kcal": 27},
                 "soup": {"name": "Soup", "kcal": 115}, "cake": {"name": "Cake", "kcal": 300}}
    refs = {"stew": {"kcal": 500, "status": "ok"},     # +40%, +200 kcal: off
            "salad": {"kcal": 20, "status": "ok"},     # +35% but 7 kcal: fine
            "soup": {"kcal": 100, "status": "ok"},     # +15%: fine
            "cake": {"kcal": 400, "status": "ok"}}     # -25%, -100 kcal: off
    result = check.check(templates, refs)
    assert [r["id"] for r in result["flagged"]] == ["stew", "cake"]
    assert result["ok"] == 2


def test_the_line_is_13_percent():
    templates = {"pasta": {"name": "Pasta", "kcal": 700}, "risotto": {"name": "Risotto", "kcal": 560}}
    refs = {"pasta": {"kcal": 610, "status": "ok"},    # +14.8%, +90 kcal: off since 25 Nov 2026
            "risotto": {"kcal": 500, "status": "ok"}}  # +12%: fine
    result = check.check(templates, refs)
    assert [r["id"] for r in result["flagged"]] == ["pasta"]


def test_new_templates_and_uncomparable_references_are_listed_apart():
    templates = {"new_dish": {"name": "New Dish", "kcal": 300},
                 "adobo": {"name": "Adobo", "kcal": 900},
                 "gyoza": {"name": "Gyoza", "kcal": 40}}
    refs = {"adobo": {"kcal": 1211, "status": "not_comparable"},
            "gyoza": {"kcal": None, "status": "none"}}
    result = check.check(templates, refs)
    assert [r["id"] for r in result["missing"]] == ["new_dish"]
    assert [r["status"] for r in result["unchecked"]] == ["not_comparable", "none"]
    assert result["flagged"] == []


def test_recipe_matches_are_compared_but_counted_apart():
    # A recipe's own amounts with our rows checks our amounts, not our
    # calorie data, so it isn't counted as an independent check (25 Nov 2026).
    templates = {"adobo": {"name": "Adobo", "kcal": 900},
                 "tinola": {"name": "Tinola", "kcal": 300},
                 "tapa": {"name": "Tapa", "kcal": 50}}
    refs = {"adobo": {"kcal": 903, "status": "recipe_match"},
            "tinola": {"kcal": 421, "status": "recipe_match"},
            "tapa": {"kcal": 44, "status": "ok"}}
    result = check.check(templates, refs)
    assert (result["ok"], result["recipe_match"]) == (1, 1)
    assert [(r["id"], r["status"]) for r in result["flagged"]] == [("tinola", "recipe_match")]


def test_the_repo_references_name_real_templates_with_usable_fields():
    with open(check.DEFAULT_REFERENCES, encoding="utf-8") as f:
        refs = json.load(f)["templates"]
    assert refs, "calorie_references.json has no templates"
    for tid, ref in refs.items():
        assert ref["status"] in {"ok", "recipe_match", "serving_differs", "not_comparable", "none"}, tid
        if ref["status"] in check.COMPARED:
            assert ref["kcal"] and ref["kcal"] > 0, tid
            assert ref["url"], tid


def test_main_runs_on_a_file_and_skips_without_references(tmp_path, capsys):
    out = tmp_path / "out.csv"
    write_output(out, [("stew", "Stew", 700)])
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps({"templates": {"stew": {"kcal": 500, "status": "ok"}}}))
    report = tmp_path / "report.json"
    assert check.main([str(out), "--references", str(refs), "--json", str(report)]) == 0
    assert json.loads(report.read_text())["flagged"][0]["id"] == "stew"
    assert check.main([str(out), "--references", str(tmp_path / "none.json")]) == 0
    assert "skipped" in capsys.readouterr().out
