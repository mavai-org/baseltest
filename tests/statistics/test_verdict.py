"""Edge-case and validation tests for verdict evaluation."""

import pytest

from baseltest.statistics import Verdict, evaluate_compliance, evaluate_regression


def test_compliance_zero_successes_fails_a_positive_threshold() -> None:
    result = evaluate_compliance(successes=0, trials=50, threshold=0.9)
    assert result.verdict is Verdict.FAIL


def test_compliance_zero_successes_passes_a_zero_threshold() -> None:
    result = evaluate_compliance(successes=0, trials=50, threshold=0.0)
    assert result.verdict is Verdict.PASS


def test_compliance_all_successes_passes_if_it_clears_the_threshold() -> None:
    result = evaluate_compliance(successes=50, trials=50, threshold=0.9)
    assert result.verdict is Verdict.PASS


def test_compliance_zero_threshold_does_not_raise_and_reports_a_neutral_diagnostic() -> None:
    result = evaluate_compliance(successes=10, trials=10, threshold=0.0)
    assert result.z_statistic == 0.0
    assert result.p_value == pytest.approx(0.5)


def test_compliance_one_threshold_does_not_raise() -> None:
    result = evaluate_compliance(successes=5, trials=10, threshold=1.0)
    assert result.verdict is Verdict.FAIL
    assert result.z_statistic == 0.0


def test_compliance_false_positive_probability_is_the_derivation_confidence_complement() -> None:
    passing = evaluate_compliance(successes=48, trials=50, threshold=0.9, confidence_level=0.95)
    failing = evaluate_compliance(successes=40, trials=50, threshold=0.9, confidence_level=0.95)
    assert passing.false_positive_probability == pytest.approx(0.05)
    assert failing.false_positive_probability == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("successes", "trials"),
    [(-1, 10), (11, 10), (0, 0)],
)
def test_compliance_rejects_invalid_counts(successes: int, trials: int) -> None:
    with pytest.raises(ValueError):
        evaluate_compliance(successes=successes, trials=trials, threshold=0.9)


def test_regression_passes_when_count_meets_cutoff() -> None:
    result = evaluate_regression(successes=44, trials=50, cutoff=44)
    assert result.verdict is Verdict.PASS


def test_regression_fails_when_count_below_cutoff() -> None:
    result = evaluate_regression(successes=43, trials=50, cutoff=44)
    assert result.verdict is Verdict.FAIL


def test_regression_rate_is_informational_only() -> None:
    # Two runs with the same rate but different cutoffs can land on opposite
    # verdicts -- the integer count against the cutoff is what decides.
    passes = evaluate_regression(successes=90, trials=100, cutoff=90)
    fails = evaluate_regression(successes=90, trials=100, cutoff=91)
    assert passes.verdict is Verdict.PASS
    assert fails.verdict is Verdict.FAIL
    assert passes.observed_rate == fails.observed_rate


def test_regression_rejects_cutoff_outside_range() -> None:
    with pytest.raises(ValueError):
        evaluate_regression(successes=5, trials=10, cutoff=11)


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_compliance_rejects_threshold_outside_unit_interval(threshold: float) -> None:
    with pytest.raises(ValueError):
        evaluate_compliance(successes=5, trials=10, threshold=threshold)


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.1, 1.1])
def test_compliance_rejects_invalid_confidence(confidence_level: float) -> None:
    with pytest.raises(ValueError):
        evaluate_compliance(
            successes=5, trials=10, threshold=0.5, confidence_level=confidence_level
        )
