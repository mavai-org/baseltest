"""Edge-case and validation tests for threshold derivation."""

import pytest

from baseltest.statistics import (
    DerivationApproach,
    derive_confidence_first,
    derive_sample_size_first,
    derive_threshold_first,
    effective_baseline_rate,
    wilson_lower_bound_from_rate,
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


class TestEffectiveBaselineRate:
    """The rate a baseline is reasoned from, at both ends of its range.

    The two boundaries are not mirror images, and the asymmetry is why a
    perfect baseline can be sized against and a baseline of no successes
    cannot.
    """

    def test_a_perfect_baseline_reduces_to_its_wilson_lower_bound(self):  # type: ignore[no-untyped-def]
        # The closed form for k == n is n / (n + z**2).
        assert effective_baseline_rate(10, 10, 0.95) == pytest.approx(0.787058029916593)
        assert effective_baseline_rate(1000, 1000, 0.95) == pytest.approx(0.9973017567602394)

    def test_a_perfect_baseline_never_reaches_one(self):  # type: ignore[no-untyped-def]
        """Which is what makes it sizeable: the sizing construction needs a
        rate strictly below the baseline, and there is room below this."""
        for trials in (1, 5, 100, 10_000):
            assert 0.0 < effective_baseline_rate(trials, trials, 0.95) < 1.0

    def test_a_baseline_with_no_successes_is_exactly_zero(self):  # type: ignore[no-untyped-def]
        """Not an artefact of rounding: at k = 0 the Wilson half-width
        equals the centre, so the lower bound is zero identically — at every
        size and every confidence. There is no room below it, which is why
        such a baseline is refused rather than reduced."""
        for trials in (1, 5, 100, 10_000):
            for confidence in (0.9, 0.95, 0.99):
                assert effective_baseline_rate(0, trials, confidence) == 0.0

    def test_an_ordinary_baseline_is_its_raw_ratio(self):  # type: ignore[no-untyped-def]
        assert effective_baseline_rate(9, 10, 0.95) == pytest.approx(0.9)
        assert effective_baseline_rate(87, 100, 0.95) == pytest.approx(0.87)


class TestOneReductionSharedByBothCallers:
    def test_sizing_and_threshold_derivation_reason_from_the_same_baseline(self):  # type: ignore[no-untyped-def]
        """Threshold derivation and run sizing must not hold two copies of
        the perfect-baseline rule: two copies that agree today are two
        copies free to drift, on the one branch no ordinary run exercises.
        """
        from baseltest.declarative._sizing import _criteria, _rates

        # One function object, reached from both sides — not two definitions
        # that happen to agree.
        assert _criteria.effective_baseline_rate is effective_baseline_rate
        assert not hasattr(_rates, "_effective_rate")

        # And the surviving one is what threshold derivation reasons from.
        derived = derive_sample_size_first(10, 10, 100, 0.95)
        assert derived.min_pass_rate == pytest.approx(
            wilson_lower_bound_from_rate(effective_baseline_rate(10, 10, 0.95), 100, 0.95)
        )
