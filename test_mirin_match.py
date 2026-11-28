"""Mirin is a typical aji-mirin, not the weakest bottle (28 Nov 2026).

A built-in boost ("mirin" -> "mirin sweet rice wine") and a boosts.json
rule setting its tablespoon (17 g) sent tbsp and tsp lines to Allied Old
English's "MIRIN SWEET COOKING RICE WINE", 150 kcal/100 g, about half what
Kikkoman (233) and Mizkan (300) print and below Japan's hon-mirin (241,
MEXT). Without it the search's own pick is Kikkoman Aji-Mirin. Both rules
are gone; this keeps them from coming back.
"""

import json
import os

import recipe_matcher as matcher

HERE = os.path.dirname(os.path.abspath(__file__))


def test_no_active_rule_steers_mirin():
    rules = matcher.load_boosts(os.path.join(HERE, "boosts.json"))
    steering = [r for r in rules
                if not r.get("_disabled") and r.get("trigger") == "mirin"]
    assert steering == []
