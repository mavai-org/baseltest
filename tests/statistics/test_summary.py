"""Edge-case tests for multi-run false-positive summary.

No mavai-R fixture dedicated to this primitive was available at the time of
writing (only cross-cutting scenario fixtures that bundle it with other
concerns), so this primitive is covered by unit tests against the closed-form
formula stated in the catalog entry, rather than an oracle conformance test.
"""

import pytest

from baseltest.statistics import RunOutcome, Verdict, summarize_runs


def test_empty_suite_has_no_false_positive_risk() -> None:
    result = summarize_runs([])
    assert result.combined_false_positive_probability == 0.0
    assert result.total_tests == 0


def test_single_passing_test_equals_its_own_probability() -> None:
    result = summarize_runs([RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05)])
    assert result.combined_false_positive_probability == pytest.approx(0.05)


def test_all_failed_tests_have_no_false_positive_risk() -> None:
    outcomes = [
        RunOutcome(verdict=Verdict.FAIL, false_positive_probability=0.05),
        RunOutcome(verdict=Verdict.FAIL, false_positive_probability=0.10),
    ]
    result = summarize_runs(outcomes)
    assert result.combined_false_positive_probability == 0.0
    assert result.failed == 2
    assert result.passed == 0


def test_zero_probability_pass_contributes_no_risk() -> None:
    outcomes = [
        RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.0),
        RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05),
    ]
    result = summarize_runs(outcomes)
    assert result.combined_false_positive_probability == pytest.approx(0.05)


def _expected_combined_probability(individual_probability: float, count: int) -> float:
    return 1 - (1 - individual_probability) ** count


def test_combined_probability_matches_multiple_comparisons_example() -> None:
    outcomes = [
        RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05) for _ in range(10)
    ]
    result = summarize_runs(outcomes)
    assert result.combined_false_positive_probability == pytest.approx(
        _expected_combined_probability(0.05, 10)
    )


def test_combined_probability_is_monotonically_non_decreasing() -> None:
    base = [RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05) for _ in range(3)]
    extended = base + [RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05)]

    smaller = summarize_runs(base)
    larger = summarize_runs(extended)
    assert larger.combined_false_positive_probability >= smaller.combined_false_positive_probability


def test_inconclusive_tests_are_excluded_from_the_product_but_counted() -> None:
    outcomes = [
        RunOutcome(verdict=Verdict.PASS, false_positive_probability=0.05),
        RunOutcome(verdict=Verdict.INCONCLUSIVE, false_positive_probability=0.0),
    ]
    result = summarize_runs(outcomes)
    assert result.combined_false_positive_probability == pytest.approx(0.05)
    assert result.inconclusive == 1
    assert result.total_tests == 2
