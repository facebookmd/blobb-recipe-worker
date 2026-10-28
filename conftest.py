"""Tests count frying oil with a fixed fry_types table, not the live one
(fry_rates.py); test_frying_oil.py's live test reads the real table."""

from __future__ import annotations

import pytest

import fry_rates

# A test fixture, not a copy the product reads: the rates the tests' oil
# amounts are worked out from.
FRY_TYPES = [
    {"key": key, "label": key, "rule_label": key, "rate": rate,
     "sort_order": i * 10, "sources_summary": ""}
    for i, (key, rate) in enumerate([
        ("fatty cut", 0.0), ("thick-cut", 0.05), ("unbreaded", 0.05),
        ("starch-dusted", 0.08), ("pan-fried fish", 0.08), ("unbreaded veg", 0.10),
        ("breaded", 0.12), ("wrapped", 0.12), ("thin-sliced", 0.13), ("battered", 0.15),
    ], start=1)
]


@pytest.fixture(autouse=True)
def fixed_fry_types(request):
    if request.node.get_closest_marker("live_fry_types"):
        fry_rates.set_for_tests(None)
    else:
        fry_rates.set_for_tests(FRY_TYPES)
    yield
    fry_rates.set_for_tests(None)


def pytest_configure(config):
    config.addinivalue_line("markers", "live_fry_types: reads the real fry_types table")
