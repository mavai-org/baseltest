"""Edge-case and validation tests for risk-driven sizing against the moving floor."""

import pytest

from baseltest.statistics import detectable_rate, power_at, required_samples_for_power


def test_power_increases_with_sample_size() -> None:
    powers = [power_at(n, 0.96, 0.93, 0.95) for n in (50, 150, 405, 1000)]
    assert powers == sorted(powers)
    assert powers[0] < powers[-1]


def test_power_is_a_probability() -> None:
    for n in (1, 10, 100, 5000):
        assert 0.0 <= power_at(n, 0.9, 0.8, 0.95) <= 1.0


def test_power_rejects_non_positive_sample_size() -> None:
    with pytest.raises(ValueError, match="sample_size"):
        power_at(0, 0.9, 0.8, 0.95)


def test_power_rejects_tolerance_at_or_above_baseline() -> None:
    with pytest.raises(ValueError, match="re-measure the baseline"):
        power_at(100, 0.9, 0.9, 0.95)
    with pytest.raises(ValueError, match="re-measure the baseline"):
        power_at(100, 0.9, 0.95, 0.95)


def test_power_rejects_perfect_baseline() -> None:
    with pytest.raises(ValueError, match="baseline_rate"):
        power_at(100, 1.0, 0.9, 0.95)


def test_required_samples_is_minimal() -> None:
    n = required_samples_for_power(0.87, 0.84, 0.95, 0.8)
    assert power_at(n, 0.87, 0.84, 0.95) >= 0.8
    assert power_at(n - 1, 0.87, 0.84, 0.95) < 0.8


def test_tighter_tolerance_requires_more_samples() -> None:
    wide = required_samples_for_power(0.96, 0.90, 0.95, 0.8)
    tight = required_samples_for_power(0.96, 0.93, 0.95, 0.8)
    assert tight > wide


def test_higher_target_power_requires_more_samples() -> None:
    modest = required_samples_for_power(0.96, 0.93, 0.95, 0.8)
    demanding = required_samples_for_power(0.96, 0.93, 0.95, 0.9)
    assert demanding > modest


def test_required_samples_rejects_tolerance_at_baseline() -> None:
    with pytest.raises(ValueError, match="re-measure the baseline"):
        required_samples_for_power(0.9, 0.9, 0.95, 0.8)


def test_required_samples_rejects_invalid_target_power() -> None:
    with pytest.raises(ValueError, match="target_power"):
        required_samples_for_power(0.9, 0.8, 0.95, 1.0)


def test_required_samples_caps_a_hopeless_search_with_a_clear_message() -> None:
    with pytest.raises(ValueError, match="too close"):
        required_samples_for_power(0.9, 0.8999999999, 0.95, 0.8)


def test_detectable_rate_round_trips_through_required_samples() -> None:
    n = required_samples_for_power(0.87, 0.84, 0.95, 0.8)
    rate = detectable_rate(n, 0.87, 0.95, 0.8)
    assert rate == pytest.approx(0.84, abs=1e-3)
    assert power_at(n, 0.87, rate, 0.95) >= 0.8


def test_detectable_rate_rises_with_sample_size() -> None:
    coarse = detectable_rate(100, 0.87, 0.95, 0.8)
    fine = detectable_rate(891, 0.87, 0.95, 0.8)
    assert fine > coarse


def test_detectable_rate_stays_below_baseline() -> None:
    rate = detectable_rate(10_000, 0.87, 0.95, 0.8)
    assert 0.0 < rate < 0.87


def test_detectable_rate_rejects_non_positive_sample_size() -> None:
    with pytest.raises(ValueError, match="sample_size"):
        detectable_rate(0, 0.9, 0.95, 0.8)


def test_detectable_rate_rejects_degenerate_baseline() -> None:
    with pytest.raises(ValueError, match="baseline_rate"):
        detectable_rate(100, 1.0, 0.95, 0.8)
