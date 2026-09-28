"""Edge-case and validation tests for the exact-binomial feasibility gate."""

import pytest

from baseltest.statistics import check_feasibility, minimum_feasible_samples


@pytest.mark.parametrize(
    ("requirement", "minimum"),
    [(0.50, 5), (0.80, 14), (0.90, 29), (0.95, 59), (0.99, 299), (0.995, 598), (0.999, 2995)],
)
def test_minimum_matches_the_companion_table_at_alpha_005(requirement: float, minimum: int) -> None:
    assert minimum_feasible_samples(requirement, 0.05) == minimum


def test_feasible_iff_at_or_above_the_minimum() -> None:
    assert check_feasibility(0.95, 59, 0.05).feasible
    assert not check_feasibility(0.95, 58, 0.05).feasible


def test_an_exact_boundary_is_feasible_under_the_inclusive_rule() -> None:
    # 0.5 ** 5 == 1/32 == alpha exactly.
    assert check_feasibility(0.5, 5, 0.03125).feasible


def test_the_criterion_is_named() -> None:
    assert check_feasibility(0.9, 30, 0.05).criterion == "exact_binomial_pass_possible"


@pytest.mark.parametrize("requirement", [0.0, 1.0, float("nan")])
def test_rejects_a_requirement_outside_the_open_interval(requirement: float) -> None:
    with pytest.raises(ValueError):
        check_feasibility(requirement, 10, 0.05)


def test_rejects_a_non_positive_sample_size() -> None:
    with pytest.raises(ValueError, match="sample_size"):
        check_feasibility(0.9, 0, 0.05)
