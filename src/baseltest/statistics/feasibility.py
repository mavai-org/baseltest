"""Feasibility checking for a probabilistic test configuration.

Answers "given this sample size, confidence level, and target pass rate,
is this test capable of producing a reliable verdict?" -- before any
samples are spent running it.

Two independent checks feed the overall verdict:

- **Confidence floor**: the configured confidence level must be at least
  the soundness floor (80%). Below that, the test has too great a
  chance of a false positive to be trustworthy.
- **Sample size adequacy**: a hypothetical perfect run (every sample
  passing) must still clear the target when reduced by sampling
  uncertainty at the configured confidence -- i.e. the one-sided Wilson
  lower bound of a perfect observation at this sample size must reach
  the target. If even a perfect run can't clear the target, no result
  from this configuration can be trusted.
"""

import math
from dataclasses import dataclass

from scipy.stats import norm

from ._constants import SOUNDNESS_FLOOR_CONFIDENCE
from .wilson import wilson_lower_bound_from_rate


@dataclass(frozen=True, slots=True)
class FeasibilityCheck:
    """The result of checking whether a test configuration is sound."""

    feasible: bool
    meets_confidence_floor: bool
    sample_size_adequate: bool
    minimum_samples: int
    sample_size: int
    confidence_level: float
    target_proportion: float
    criterion: str = "wilson_score_one_sided_lower_bound"


def check_feasibility(
    sample_size: int,
    target_proportion: float,
    confidence_level: float = 0.95,
) -> FeasibilityCheck:
    """Check whether a test configuration is statistically sound.

    Args:
        sample_size: The number of samples the test plans to run. Must
            be positive.
        target_proportion: The pass-rate threshold the test must clear,
            in `[0, 1)`.
        confidence_level: The confidence level the test will use,
            strictly between 0 and 1.

    Returns:
        A `FeasibilityCheck` reporting whether the configuration is
        feasible overall, plus the two contributing checks and the
        minimum sample size that would make the configuration
        adequate at this confidence and target.

    Raises:
        ValueError: If `sample_size` is not positive, `target_proportion`
            is outside `[0, 1)`, or `confidence_level` is not strictly
            between 0 and 1.
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    if math.isnan(target_proportion) or not (0.0 <= target_proportion < 1.0):
        raise ValueError("target_proportion must be in [0, 1)")
    if math.isnan(confidence_level) or not (0.0 < confidence_level < 1.0):
        raise ValueError("confidence_level must be strictly between 0 and 1")

    alpha = 1 - confidence_level
    z = float(norm.ppf(1 - alpha))
    z_squared = z * z

    minimum_samples = math.ceil(target_proportion * z_squared / (1 - target_proportion))
    lower_bound = wilson_lower_bound_from_rate(1.0, sample_size, confidence_level)
    sample_size_adequate = lower_bound >= target_proportion
    meets_confidence_floor = confidence_level >= SOUNDNESS_FLOOR_CONFIDENCE

    return FeasibilityCheck(
        feasible=meets_confidence_floor and sample_size_adequate,
        meets_confidence_floor=meets_confidence_floor,
        sample_size_adequate=sample_size_adequate,
        minimum_samples=minimum_samples,
        sample_size=sample_size,
        confidence_level=confidence_level,
        target_proportion=target_proportion,
    )
