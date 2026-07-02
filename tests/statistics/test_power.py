"""Edge-case and validation tests for power analysis / sample size calculation."""

import pytest

from baseltest.statistics import achieved_power, required_sample_size


def test_required_sample_size_round_trips_through_achieved_power() -> None:
    n = required_sample_size(confidence_level=0.95, effect_size=0.05, power=0.8, baseline_rate=0.95)
    power = achieved_power(
        sample_size=n, confidence_level=0.95, effect_size=0.05, baseline_rate=0.95
    )
    assert power >= 0.8


def test_smaller_effect_size_requires_more_samples() -> None:
    small_effect = required_sample_size(
        confidence_level=0.95, effect_size=0.02, power=0.8, baseline_rate=0.95
    )
    large_effect = required_sample_size(
        confidence_level=0.95, effect_size=0.10, power=0.8, baseline_rate=0.95
    )
    assert small_effect > large_effect


def test_higher_power_requires_more_samples() -> None:
    low_power = required_sample_size(
        confidence_level=0.95, effect_size=0.05, power=0.5, baseline_rate=0.95
    )
    high_power = required_sample_size(
        confidence_level=0.95, effect_size=0.05, power=0.95, baseline_rate=0.95
    )
    assert high_power > low_power


def test_required_sample_size_rejects_zero_effect_size() -> None:
    with pytest.raises(ValueError):
        required_sample_size(confidence_level=0.95, effect_size=0.0, power=0.8, baseline_rate=0.95)


def test_required_sample_size_rejects_full_power() -> None:
    with pytest.raises(ValueError):
        required_sample_size(confidence_level=0.95, effect_size=0.05, power=1.0, baseline_rate=0.95)


def test_required_sample_size_rejects_effect_exceeding_baseline() -> None:
    with pytest.raises(ValueError):
        required_sample_size(confidence_level=0.95, effect_size=0.5, power=0.8, baseline_rate=0.3)


@pytest.mark.parametrize("baseline_rate", [0.0, -0.1, 1.1])
def test_required_sample_size_rejects_invalid_baseline_rate(baseline_rate: float) -> None:
    with pytest.raises(ValueError):
        required_sample_size(
            confidence_level=0.95, effect_size=0.05, power=0.8, baseline_rate=baseline_rate
        )


def test_required_sample_size_allows_perfect_baseline() -> None:
    n = required_sample_size(confidence_level=0.95, effect_size=0.05, power=0.8, baseline_rate=1.0)
    assert n > 0


def test_achieved_power_large_sample_approaches_one() -> None:
    power = achieved_power(
        sample_size=100_000, confidence_level=0.95, effect_size=0.05, baseline_rate=0.95
    )
    assert power > 0.999


def test_achieved_power_tiny_sample_has_little_detection_capability() -> None:
    power = achieved_power(
        sample_size=2, confidence_level=0.95, effect_size=0.05, baseline_rate=0.95
    )
    assert power < 0.5


def test_achieved_power_rejects_non_positive_sample_size() -> None:
    with pytest.raises(ValueError):
        achieved_power(sample_size=0, confidence_level=0.95, effect_size=0.05, baseline_rate=0.95)
