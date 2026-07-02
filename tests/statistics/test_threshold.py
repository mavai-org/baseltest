"""Edge-case and validation tests for threshold derivation."""

import pytest

from baseltest.statistics import (
    DerivationApproach,
    derive_confidence_first,
    derive_sample_size_first,
    derive_threshold_first,
)


def test_sample_size_first_perfect_baseline_keeps_threshold_below_one() -> None:
    result = derive_sample_size_first(
        baseline_successes=20, baseline_trials=20, test_samples=50, confidence_level=0.95
    )
    assert result.approach is DerivationApproach.SAMPLE_SIZE_FIRST
    assert result.min_pass_rate < 1.0
    assert result.baseline_pass_rate == 1.0


def test_sample_size_first_threshold_never_exceeds_baseline_rate() -> None:
    result = derive_sample_size_first(
        baseline_successes=95, baseline_trials=100, test_samples=50, confidence_level=0.95
    )
    assert result.min_pass_rate <= result.baseline_pass_rate
    assert result.gap_from_baseline >= 0.0


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.1, 1.1])
def test_sample_size_first_rejects_invalid_confidence(confidence_level: float) -> None:
    with pytest.raises(ValueError):
        derive_sample_size_first(
            baseline_successes=95,
            baseline_trials=100,
            test_samples=50,
            confidence_level=confidence_level,
        )


def test_sample_size_first_higher_confidence_gives_lower_threshold() -> None:
    lenient = derive_sample_size_first(
        baseline_successes=95, baseline_trials=100, test_samples=50, confidence_level=0.80
    )
    strict = derive_sample_size_first(
        baseline_successes=95, baseline_trials=100, test_samples=50, confidence_level=0.99
    )
    assert strict.min_pass_rate < lenient.min_pass_rate


@pytest.mark.parametrize(
    ("baseline_successes", "baseline_trials", "test_samples"),
    [(-1, 10, 5), (11, 10, 5), (5, 0, 5), (5, 10, 0)],
)
def test_sample_size_first_rejects_invalid_input(
    baseline_successes: int, baseline_trials: int, test_samples: int
) -> None:
    with pytest.raises(ValueError):
        derive_sample_size_first(
            baseline_successes=baseline_successes,
            baseline_trials=baseline_trials,
            test_samples=test_samples,
        )


def test_threshold_first_low_threshold_implies_high_confidence() -> None:
    result = derive_threshold_first(
        baseline_successes=95, baseline_trials=100, test_samples=100, min_pass_rate=0.5
    )
    assert result.confidence_level > 0.9
    assert result.is_sound


def test_threshold_first_soundness_floor_is_shared_constant() -> None:
    # A threshold close to the baseline's raw rate is hard to back with high
    # confidence at a modest sample size -- expect an unsound result.
    result = derive_threshold_first(
        baseline_successes=95, baseline_trials=100, test_samples=100, min_pass_rate=0.94
    )
    assert result.is_sound is (result.confidence_level >= 0.80)


@pytest.mark.parametrize("min_pass_rate", [0.0, 1.0, -0.1, 1.1])
def test_threshold_first_rejects_boundary_threshold(min_pass_rate: float) -> None:
    with pytest.raises(ValueError):
        derive_threshold_first(
            baseline_successes=95,
            baseline_trials=100,
            test_samples=100,
            min_pass_rate=min_pass_rate,
        )


def test_confidence_first_delegates_to_power_analysis() -> None:
    result = derive_confidence_first(
        baseline_rate=0.95, effect_size=0.05, confidence_level=0.95, power=0.8
    )
    assert result.approach is DerivationApproach.CONFIDENCE_FIRST
    assert result.sample_size > 0
    assert result.min_pass_rate == pytest.approx(0.90)


def test_confidence_first_rejects_zero_effect_size() -> None:
    with pytest.raises(ValueError):
        derive_confidence_first(baseline_rate=0.95, effect_size=0.0)


def test_confidence_first_rejects_full_power() -> None:
    with pytest.raises(ValueError):
        derive_confidence_first(baseline_rate=0.95, effect_size=0.05, power=1.0)
