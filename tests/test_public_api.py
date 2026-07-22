"""The curated top-level ``baseltest`` surface."""

import baseltest
from baseltest import declarative


def test_top_level_exposes_the_core_entry_points() -> None:
    assert set(baseltest.__all__) == {
        "Bindings",
        "__version__",
        "check_contract",
        "explore",
        "optimize",
        "run",
    }


def test_entry_points_are_the_declarative_surface() -> None:
    # Single-sourced: the top level re-exports declarative, never a copy.
    assert baseltest.run is declarative.run
    assert baseltest.explore is declarative.explore
    assert baseltest.optimize is declarative.optimize
    assert baseltest.check_contract is declarative.check_contract
    assert baseltest.Bindings is declarative.Bindings
