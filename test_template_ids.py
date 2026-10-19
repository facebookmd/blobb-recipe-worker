"""Curated template ids: an "ID:" line pins one, so renaming a recipe keeps
its id (share links, blobb.app/?dish=<id>, and saved meals point at it), and
two recipes with one id fail instead of being merged into one template.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import parse_recipe

HERE = Path(__file__).resolve().parent
MIGRATION_TOOL = HERE.parent / "blobbapp" / "tool" / "csv_templates_to_supabase_migration.py"

OYAKODON = """\
Category: Japanese

Oyakodon
ID: chicken_and_egg_rice_bowl
AKA: Chicken and Egg Rice Bowl
Servings: 2
1 cup cooked rice
2 large egg
"""


def _write(tmp_path: Path, text: str, name: str = "recipes.txt") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _ids(recipes) -> list[str]:
    return [meta["template_id"] for meta, _ in recipes]


# ── parser ──────────────────────────────────────────────────────────────────

def test_id_line_pins_the_id(tmp_path):
    [(meta, ingredients)] = parse_recipe.parse_file(_write(tmp_path, OYAKODON))
    assert meta["template_id"] == "chicken_and_egg_rice_bowl"
    assert meta["template_name"] == "Oyakodon"
    assert [i["ingredient"] for i in ingredients] == ["cooked rice", "egg"]


def test_renaming_the_title_keeps_the_id(tmp_path):
    renamed = OYAKODON.replace("\nOyakodon\n", "\nChicken Rice Bowl\n")
    [(meta, _)] = parse_recipe.parse_file(_write(tmp_path, renamed))
    assert meta["template_name"] == "Chicken Rice Bowl"
    assert meta["template_id"] == "chicken_and_egg_rice_bowl"


def test_without_an_id_line_the_title_is_slugified(tmp_path):
    text = OYAKODON.replace("ID: chicken_and_egg_rice_bowl\n", "")
    [(meta, _)] = parse_recipe.parse_file(_write(tmp_path, text))
    assert meta["template_id"] == "oyakodon_"


def test_id_line_is_not_an_ingredient_or_title(tmp_path):
    # Above the title, and in any case: still the id, never the title.
    text = "id: miso_soup\nMiso Soup\n1 tbsp miso\n"
    [(meta, ingredients)] = parse_recipe.parse_file(_write(tmp_path, text))
    assert meta["template_id"] == "miso_soup"
    assert meta["template_name"] == "Miso Soup"
    assert [i["ingredient"] for i in ingredients] == ["miso"]


@pytest.mark.parametrize("bad", ["", "Chicken Bowl", "Oyakodon", "_x", "a/b"])
def test_a_malformed_id_is_refused(tmp_path, bad):
    text = OYAKODON.replace("ID: chicken_and_egg_rice_bowl", f"ID: {bad}")
    with pytest.raises(parse_recipe.RecipeFormatError, match="isn't an ID"):
        parse_recipe.parse_file(_write(tmp_path, text))


def test_two_recipes_with_one_slug_are_refused_naming_both(tmp_path):
    text = "Miso Soup\n1 tbsp miso\n\n\n\nMiso-Soup\n2 tbsp red miso\n"
    recipes = parse_recipe.parse_file(_write(tmp_path, text))
    assert _ids(recipes) == ["miso_soup", "miso_soup"]
    with pytest.raises(parse_recipe.RecipeFormatError,
                       match="'Miso Soup' and 'Miso-Soup' both have ID miso_soup"):
        parse_recipe.check_unique_ids(recipes)


def test_a_pinned_id_clashing_with_another_title_is_refused(tmp_path):
    text = OYAKODON + "\n\n\nChicken and Egg Rice Bowl\n1 cup rice\n"
    recipes = parse_recipe.parse_file(_write(tmp_path, text))
    with pytest.raises(parse_recipe.RecipeFormatError,
                       match="'Oyakodon' and 'Chicken and Egg Rice Bowl' both "
                             "have ID chicken_and_egg_rice_bowl"):
        parse_recipe.check_unique_ids(recipes)


def test_distinct_ids_pass():
    recipes = [({"template_id": "a_b", "template_name": "A B"}, []),
               ({"template_id": "a_c", "template_name": "A C"}, [])]
    parse_recipe.check_unique_ids(recipes)


def _batch(tmp_path, *files: str) -> subprocess.CompletedProcess:
    out = tmp_path / "recipes.csv"
    return subprocess.run(
        [sys.executable, str(HERE / "parse_recipe.py"), *files,
         "--yes", "--forceall", "--parse-only", "--recipes-out", str(out),
         "--output", str(tmp_path / "out.xlsx")],
        capture_output=True, text=True, cwd=tmp_path)


def test_batch_run_after_a_rename_keeps_the_id(tmp_path):
    renamed = OYAKODON.replace("\nOyakodon\n", "\nChicken Rice Bowl\n")
    result = _batch(tmp_path, _write(tmp_path, renamed))
    assert result.returncode == 0, result.stderr
    with (tmp_path / "recipes.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {(r["template_id"], r["template_name"]) for r in rows} == {
        ("chicken_and_egg_rice_bowl", "Chicken Rice Bowl")}


def test_batch_run_refuses_one_id_across_two_files(tmp_path):
    first = _write(tmp_path, OYAKODON, "a.txt")
    second = _write(tmp_path, "Chicken and Egg Rice Bowl\n1 cup rice\n", "b.txt")
    result = _batch(tmp_path, first, second)
    assert result.returncode == 1
    assert ("'Oyakodon' and 'Chicken and Egg Rice Bowl' both have ID "
            "chicken_and_egg_rice_bowl") in result.stderr
    assert not (tmp_path / "recipes.csv").exists()


def test_every_recipe_in_the_recipe_files_pins_a_unique_id():
    files = sorted((HERE.parent / "recipes").glob("*_recipes.txt"))
    if not files:
        pytest.skip("no recipe files next to templates/")
    recipes = [r for f in files for r in parse_recipe.parse_file(str(f))]
    unpinned = [m["template_name"] for m, _ in recipes if not m["id_pinned"]]
    assert unpinned == []
    parse_recipe.check_unique_ids(recipes)


# ── import tool (blobbapp/tool) ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def migration():
    if not MIGRATION_TOOL.exists():
        pytest.skip("blobbapp/ isn't next to templates/")
    spec = importlib.util.spec_from_file_location("migration_tool", MIGRATION_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADER = ["_type", "template_id", "template_name", "component_label",
          "matched_food_name", "food_id", "portion_amt", "unit_label",
          "unit_grams", "cal_tot", "section"]


def _csv(tmp_path, rows) -> Path:
    path = tmp_path / "templates_output.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def _data(tid, name, label):
    return ["data", tid, name, label, label, "172442", "1", "tbsp", "17", "34", "Main"]


def _total(tid):
    return ["subtotal", tid, "", "", "", "", "", "", "", "68", ""]


def test_import_refuses_two_recipes_under_one_id(tmp_path, migration):
    path = _csv(tmp_path, [
        _data("miso_soup", "Miso Soup", "miso"), _data("miso_soup", "Miso Soup", "tofu"),
        _total("miso_soup"),
        _data("miso_soup", "Miso-Soup", "red miso"), _data("miso_soup", "Miso-Soup", "clams"),
        _total("miso_soup"),
    ])
    templates, problems = migration.load_rows(path)
    assert problems == ["'Miso Soup' and 'Miso-Soup' both have ID miso_soup "
                        "(give one its own 'ID:' line)"]


def test_import_refuses_a_second_block_with_the_same_name(tmp_path, migration):
    path = _csv(tmp_path, [
        _data("miso_soup", "Miso Soup", "miso"), _total("miso_soup"),
        _data("gyoza_", "Gyoza", "pork"), _total("gyoza_"),
        _data("miso_soup", "Miso Soup", "tofu"), _total("miso_soup"),
    ])
    _, problems = migration.load_rows(path)
    assert problems == ["'Miso Soup' and 'Miso Soup' both have ID miso_soup "
                        "(give one its own 'ID:' line)"]


def test_import_accepts_one_recipe_per_id(tmp_path, migration):
    path = _csv(tmp_path, [
        _data("miso_soup", "Miso Soup", "miso"), _data("miso_soup", "Miso Soup", "tofu"),
        _total("miso_soup"),
        _data("gyoza_", "Gyoza", "pork"), _total("gyoza_"),
    ])
    templates, problems = migration.load_rows(path)
    assert problems == []
    assert {k: len(t["components"]) for k, t in templates.items()} == {
        "miso_soup": 2, "gyoza_": 1}


def test_import_cli_writes_nothing_on_a_duplicate(tmp_path, migration):
    path = _csv(tmp_path, [
        _data("miso_soup", "Miso Soup", "miso"), _total("miso_soup"),
        _data("miso_soup", "Miso-Soup", "clams"), _total("miso_soup"),
    ])
    out = tmp_path / "import.sql"
    result = subprocess.run(
        [sys.executable, str(MIGRATION_TOOL), "--input", str(path), "--output", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 1
    assert "'Miso Soup' and 'Miso-Soup' both have ID miso_soup" in result.stderr
    assert not out.exists()
