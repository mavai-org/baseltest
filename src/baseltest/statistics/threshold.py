"""Threshold derivation: turning two of {sample size, confidence, threshold}
into the third.

A probabilistic test needs a pass-rate threshold, a sample size, and a
confidence level. Developers rarely want to set all three by hand, so this
module offers three ways in, each solving for the value the other two imply:

- `derive_sample_size_first` -- given a baseline and a planned sample size,
  derive the threshold (the common case: "I know how many samples I'll run,
  what pass rate should I require?").
- `derive_threshold_first` -- given a baseline, a sample size, and an
  explicit threshold, derive the confidence that threshold is actually
  backed by ("I want to require 90% -- how confident can I be in that?").
- `derive_confidence_first` -- given a baseline, an effect size worth
  detecting, a desired power and confidence, derive both the sample size
  and the resulting threshold ("I want to reliably detect a 5-point drop --
  how many samples do I need, and what pass rate does that imply?").

All three share one building block: the *effective baseline rate*. When the
baseline itself is a perfect run (every sample passed), its raw rate of 1.0
overstates how much is really known -- a coin that came up heads five times
in a row isn't proven to always land heads. In that case the baseline's own
one-sided Wilson lower bound is used as the effective rate instead of the
raw ratio, so a small perfect baseline doesn't produce a threshold that is
falsely close to 1.0.
"""

import math
from dataclasses import dataclass
from enum import Enum

from ._constants import SOUNDNESS_FLOOR_CONFIDENCE
from .power import required_sample_size
from .wilson import wilson_lower_bound, wilson_lower_bound_from_rate


class DerivationApproach(Enum):
    """Which of the three threshold-derivation modes produced a result."""

    SAMPLE_SIZE_FIRST = "sample_size_first"
    THRESHOLD_FIRST = "threshold_first"
    CONFIDENCE_FIRST = "confidence_first"


def _validate_baseline(baseline_successes: int, baseline_trials: int) -> None:
    if baseline_trials <= 0:
        raise ValueError("baseline_trials must be a positive integer")
    if baseline_successes < 0:
        raise ValueError("baseline_successes must be non-negative")
    if baseline_successes > baseline_trials:
        raise ValueError("baseline_successes cannot exceed baseline_trials")


def _validate_confidence_level(confidence_level: float) -> None:
    if math.isnan(confidence_level) or not (0.0 < confidence_level < 1.0):
        raise ValueError("confidence_level must be strictly between 0 and 1")


def _effective_baseline_rate(
    baseline_successes: int, baseline_trials: int, confidence_level: float
) -> float:
    if baseline_successes == baseline_trials:
        return wilson_lower_bound(baseline_successes, baseline_trials, confidence_level)
    return baseline_successes / baseline_trials


@dataclass(frozen=True, slots=True)
class SampleSizeFirstThreshold:
    """The threshold derived from a baseline and a declared test sample size."""

    min_pass_rate: float
    sample_size: int
    confidence_level: float
    baseline_pass_rate: float
    approach: DerivationApproach = DerivationApproach.SAMPLE_SIZE_FIRST

    @property
    def gap_from_baseline(self) -> float:
        """How much lower the derived threshold is than the raw baseline rate."""
        return self.baseline_pass_rate - self.min_pass_rate


def derive_sample_size_first(
    baseline_successes: int,
    baseline_trials: int,
    test_samples: int,
    confidence_level: float = 0.95,
) -> SampleSizeFirstThreshold:
    """Derive a pass-rate threshold from a baseline and a planned sample size.

    Args:
        baseline_successes: Successes observed in the baseline run.
        baseline_trials: Total trials in the baseline run. Must be
            positive.
        test_samples: The number of samples the test will run. Must be
            positive.
        confidence_level: Confidence level to use for both the
            baseline adjustment and the threshold construction,
            strictly between 0 and 1.

    Returns:
        The derived threshold and its context.

    Raises:
        ValueError: If the baseline counts or `test_samples` are
            invalid, or `confidence_level` is not strictly between 0
            and 1.
    """
    _validate_baseline(baseline_successes, baseline_trials)
    if test_samples <= 0:
        raise ValueError("test_samples must be a positive integer")
    _validate_confidence_level(confidence_level)

    effective_rate = _effective_baseline_rate(baseline_successes, baseline_trials, confidence_level)
    min_pass_rate = wilson_lower_bound_from_rate(effective_rate, test_samples, confidence_level)

    return SampleSizeFirstThreshold(
        min_pass_rate=min_pass_rate,
        sample_size=test_samples,
        confidence_level=confidence_level,
        baseline_pass_rate=baseline_successes / baseline_trials,
    )


@dataclass(frozen=True, slots=True)
class ThresholdFirstConfidence:
    """The confidence level implied by a declared threshold and sample size."""

    min_pass_rate: float
    sample_size: int
    confidence_level: float
    is_sound: bool
    approach: DerivationApproach = DerivationApproach.THRESHOLD_FIRST


def derive_threshold_first(
    baseline_successes: int,
    baseline_trials: int,
    test_samples: int,
    min_pass_rate: float,
    *,
    search_tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> ThresholdFirstConfidence:
    """Derive the confidence level implied by a declared threshold.

    Finds, by binary search, the confidence level `c` for which the
    same baseline-adjusted Wilson construction used by
    `derive_sample_size_first` would have produced exactly
    `min_pass_rate` at `test_samples`.

    Args:
        baseline_successes: Successes observed in the baseline run.
        baseline_trials: Total trials in the baseline run. Must be
            positive.
        test_samples: The number of samples the test will run. Must be
            positive.
        min_pass_rate: The developer-declared threshold, strictly
            between 0 and 1.
        search_tolerance: How close the binary search must land to
            `min_pass_rate` before returning.
        max_iterations: Upper bound on binary search iterations.

    Returns:
        The implied confidence level, and whether it clears the
        soundness floor.

    Raises:
        ValueError: If the baseline counts or `test_samples` are
            invalid, or `min_pass_rate` is not strictly between 0
            and 1.
    """
    _validate_baseline(baseline_successes, baseline_trials)
    if test_samples <= 0:
        raise ValueError("test_samples must be a positive integer")
    if math.isnan(min_pass_rate) or not (0.0 < min_pass_rate < 1.0):
        raise ValueError("min_pass_rate must be strictly between 0 and 1")

    low, high = 1e-6, 1.0 - 1e-6
    confidence_level = (low + high) / 2
    for _ in range(max_iterations):
        confidence_level = (low + high) / 2
        effective_rate = _effective_baseline_rate(
            baseline_successes, baseline_trials, confidence_level
        )
        candidate = wilson_lower_bound_from_rate(effective_rate, test_samples, confidence_level)
        if abs(candidate - min_pass_rate) < search_tolerance:
            break
        if candidate > min_pass_rate:
            low = confidence_level
        else:
            high = confidence_level

    return ThresholdFirstConfidence(
        min_pass_rate=min_pass_rate,
        sample_size=test_samples,
        confidence_level=confidence_level,
        is_sound=confidence_level >= SOUNDNESS_FLOOR_CONFIDENCE,
    )


@dataclass(frozen=True, slots=True)
class ConfidenceFirstThreshold:
    """The sample size and threshold implied by a target power and effect size."""

    sample_size: int
    min_pass_rate: float
    confidence_level: float
    power: float
    effect_size: float
    approach: DerivationApproach = DerivationApproach.CONFIDENCE_FIRST


def derive_confidence_first(
    baseline_rate: float,
    effect_size: float,
    confidence_level: float = 0.95,
    power: float = 0.8,
) -> ConfidenceFirstThreshold:
    """Derive the sample size and threshold needed to detect an effect size.

    Args:
        baseline_rate: The baseline (null hypothesis) pass rate, in
            `(0, 1]`.
        effect_size: The minimum decrease in pass rate worth detecting,
            strictly between 0 and 1.
        confidence_level: Desired confidence, strictly between 0 and 1.
        power: Desired power, strictly between 0 and 1.

    Returns:
        The required sample size (rounded up) and the resulting
        threshold (`baseline_rate - effect_size`).

    Raises:
        ValueError: If any input is out of range, or `effect_size` is
            at least as large as `baseline_rate`.
    """
    sample_size = required_sample_size(confidence_level, effect_size, power, baseline_rate)
    min_pass_rate = baseline_rate - effect_size

    return ConfidenceFirstThreshold(
        sample_size=sample_size,
        min_pass_rate=min_pass_rate,
        confidence_level=confidence_level,
        power=power,
        effect_size=effect_size,
    )
