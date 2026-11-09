"""The most specific boost rule wins (3 Nov 2026).

apply_boosts took the first rule that matched, and BUILTIN_BOOSTS come
before boosts.json's, so built-in "miso" (search "miso paste") took "white
miso" before the file's pin, and "adzuki" (raw) took "adzuki beans" before
its boiled pin. Now the trigger with the most words wins, then the most
letters; equal triggers go in list order, so boosts.json keeps no second
rule for a trigger an earlier one already has.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import os

import recipe_matcher as matcher

HERE = os.path.dirname(os.path.abspath(__file__))


def test_a_longer_trigger_beats_an_earlier_shorter_one():
    rules = [{"trigger": "miso", "boost": "miso paste", "weight": 0.9},
             {"trigger": "white miso", "fdc_id": "B_2053303"}]
    assert matcher.apply_boosts("white miso", rules) == ("white miso", 0.0, "B_2053303")
    assert matcher.apply_boosts("red miso", rules) == ("miso paste", 0.9, None)


def test_more_words_beat_more_letters():
    rules = [{"trigger": "adzuki", "fdc_id": "173727"},
             {"trigger": "adzuki beans", "fdc_id": "173728"}]
    assert matcher.apply_boosts("adzuki beans", rules)[2] == "173728"
    assert matcher.apply_boosts("adzuki", rules)[2] == "173727"


def test_equal_triggers_keep_list_order():
    rules = [{"trigger": "rice koji", "fdc_id": "B_1"},
             {"trigger": "koji rice", "fdc_id": "B_2"}]
    assert matcher.apply_boosts("koji rice", rules)[2] == "B_1"


def test_a_specific_rule_that_stands_aside_leaves_the_generic_one():
    rules = [{"trigger": "chili", "boost": "hot red chili pepper", "weight": 0.8},
             {"trigger": "green chili", "boost": "green chili pepper", "weight": 0.8,
              "category": "mexican"}]
    assert matcher.apply_boosts("green chili", rules, "japanese")[0] == "hot green chili pepper"
    assert matcher.apply_boosts("green chili", rules, "mexican")[0] == "green chili pepper"


def test_the_real_rules_pin_their_own_triggers():
    rules = matcher.load_boosts(os.path.join(HERE, "boosts.json"))
    assert matcher.apply_boosts("white miso", rules)[2] == "B_2053303"
    assert matcher.apply_boosts("adzuki beans", rules)[2] == "173728"
    # Plain sheets, not whole grain: Barilla's enriched lasagne, 2 sheets = 50 g.
    assert matcher.apply_boosts("lasagna noodles", rules)[2] == "B_2588023"


def test_no_rule_repeats_an_earlier_trigger():
    """A second rule for the same trigger never fires: the first one wins."""
    rules = matcher.load_boosts(os.path.join(HERE, "boosts.json"))
    seen, repeated = {}, []
    for rule in rules:
        if "trigger" not in rule or rule.get("_disabled") or not (rule.get("boost") or rule.get("fdc_id")):
            continue   # portion rules share their food's trigger
        key = (matcher.normalise(rule["trigger"]), rule.get("category", ""), bool(rule.get("exact")))
        if key in seen:
            repeated.append((seen[key], rule))
        seen.setdefault(key, rule)
    assert repeated == []


def test_kinako_is_roasted_soy_flour_however_it_is_named():
    # Kinako is roasted soy flour: "soy flour kinako" pointed at raw soy
    # flour (174273) while "kinako" pointed at roasted (3 Nov 2026).
    rules = matcher.load_boosts(os.path.join(os.path.dirname(__file__), "boosts.json"))
    pins = {r["trigger"]: r["fdc_id"] for r in rules
            if r.get("fdc_id") and "kinako" in r.get("trigger", "")}
    assert pins and set(pins.values()) == {"174274"}
