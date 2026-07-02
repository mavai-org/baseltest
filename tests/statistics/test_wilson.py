"""Edge-case and validation tests for the Wilson score interval primitives."""

import pytest

from baseltest.statistics import wilson_interval, wilson_lower_bound, wilson_lower_bound_from_rate


def test_two_sided_interval_zero_successes_has_positive_upper_bound() -> None:
    result = wilson_interval(successes=0, trials=20, confidence_level=0.95)
    assert result.lower_bound == 0.0
    assert result.upper_bound > 0.0


def test_two_sided_interval_all_successes_has_lower_bound_below_one() -> None:
    result = wilson_interval(successes=20, trials=20, confidence_level=0.95)
    assert result.upper_bound == 1.0
    assert result.lower_bound < 1.0


def test_two_sided_interval_single_trial_is_valid() -> None:
    result = wilson_interval(successes=1, trials=1, confidence_level=0.95)
    assert 0.0 <= result.lower_bound <= result.point_estimate <= result.upper_bound <= 1.0


def test_two_sided_interval_width_and_margin_of_error_are_consistent() -> None:
    result = wilson_interval(successes=50, trials=100, confidence_level=0.95)
    assert result.width == pytest.approx(result.upper_bound - result.lower_bound)
    assert result.margin_of_error == pytest.approx(result.width / 2)


def test_two_sided_interval_widens_with_confidence() -> None:
    narrow = wilson_interval(successes=50, trials=100, confidence_level=0.80)
    wide = wilson_interval(successes=50, trials=100, confidence_level=0.99)
    assert wide.width > narrow.width


@pytest.mark.parametrize(
    ("successes", "trials"),
    [(-1, 10), (11, 10), (0, 0)],
)
def test_two_sided_interval_rejects_invalid_counts(successes: int, trials: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(successes=successes, trials=trials)


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.1, 1.1])
def test_two_sided_interval_rejects_invalid_confidence(confidence_level: float) -> None:
    with pytest.raises(ValueError):
        wilson_interval(successes=5, trials=10, confidence_level=confidence_level)


def test_lower_bound_zero_successes_is_zero() -> None:
    assert wilson_lower_bound(successes=0, trials=20, confidence_level=0.95) == 0.0


def test_lower_bound_all_successes_is_close_to_but_below_one() -> None:
    result = wilson_lower_bound(successes=20, trials=20, confidence_level=0.95)
    assert 0.5 < result < 1.0


def test_lower_bound_at_half_confidence_is_close_to_point_estimate() -> None:
    result = wilson_lower_bound(successes=50, trials=100, confidence_level=0.5)
    assert result == pytest.approx(0.5, abs=0.05)


@pytest.mark.parametrize(
    ("successes", "trials"),
    [(-1, 10), (11, 10), (0, 0)],
)
def test_lower_bound_rejects_invalid_counts(successes: int, trials: int) -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound(successes=successes, trials=trials)


def test_lower_bound_from_rate_rejects_out_of_range_rate() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound_from_rate(observed_rate=1.5, trials=10)


def test_lower_bound_from_rate_rejects_nan_rate() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound_from_rate(observed_rate=float("nan"), trials=10)


def test_lower_bound_from_rate_rejects_non_positive_trials() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound_from_rate(observed_rate=0.5, trials=0)


def test_lower_bound_from_rate_does_not_require_integrality() -> None:
    # A continuous rate with no underlying (k, n) pair is a valid input --
    # this is what lets threshold derivation carry a baseline's own bound
    # forward as the reference rate for a downstream test.
    result = wilson_lower_bound_from_rate(observed_rate=0.873, trials=50)
    assert 0.0 <= result <= 0.873
