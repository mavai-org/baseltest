"""Risk-driven sizing of a regression test against the operative rule (§5.4.1).

A regression test's cutoff is derived at the test's own size, so sizing is
done against the cutoff the test will actually apply. Two operations answer
different questions and are named apart:

- **Design sizing**, before the baseline exists: the baseline is planned at
  ``n_b`` trials and an expected rate ``p0``, and the design power averages
  over the baseline count yet to be drawn.
- **Resolved sizing**, against an existing baseline: its observed count
  fixes the cutoff for every candidate test size, and the resolved power
  decides. Once a baseline exists, ``BASELINE_TOO_SMALL`` is judged by it.

The **design alternative rate** ``p_design`` is the true rate at which the
test must reach its target power — a declared design input, not a measured
estimate and not a tolerance: the test still flags any degradation from the
baseline, including one to a rate above ``p_design``.

Exact power is a sawtooth in the test size, so the required size is the
smallest ``n_t`` from which power *stays* at or above the target for every
larger test up to the baseline size — not the first crossing — subject to
the design rule ``n_t <= n_b``.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.stats import binom

from ._arrays import IntArray
from .regression import (
    _cutoffs_near,
    _fail_probability,
    baseline_window,
    design_power,
    fisher_cutoffs,
)

# Bisection resolution for the detectable-rate inversion.
_DETECTABLE_RATE_TOLERANCE = 1e-10


class SizingRefusal(StrEnum):
    """Why a sizing design cannot be priced; the value is the reported category."""

    ZERO_BASELINE = "ZERO_BASELINE"
    """The baseline observed (or expects) no successes (§4.3.4): there is no
    rate below it to detect. *Measure a baseline before sizing against it.*"""

    ALTERNATIVE_NOT_BELOW_BASELINE = "ALTERNATIVE_NOT_BELOW_BASELINE"
    """The design alternative rate is not below the baseline rate, so there
    is no degradation to detect. *Re-measure rather than raise the rate.*"""

    TEST_LARGER_THAN_BASELINE = "TEST_LARGER_THAN_BASELINE"
    """A candidate test larger than the baseline the design rule admits."""

    BASELINE_TOO_SMALL = "BASELINE_TOO_SMALL"
    """No test the design rule admits reaches and holds the target power:
    a larger baseline is needed."""


def check_sizing_domain(
    baseline_rate: float,
    baseline_trials: int,
    design_alternative_rate: float | None = None,
    test_samples: int | None = None,
) -> SizingRefusal | None:
    """The refusal a sizing design meets before any power is computed, or ``None``."""
    if baseline_rate == 0.0:
        return SizingRefusal.ZERO_BASELINE
    if design_alternative_rate is not None and design_alternative_rate >= baseline_rate:
        return SizingRefusal.ALTERNATIVE_NOT_BELOW_BASELINE
    if test_samples is not None and test_samples > baseline_trials:
        return SizingRefusal.TEST_LARGER_THAN_BASELINE
    return None


@dataclass(frozen=True, slots=True)
class DesignSizing:
    """The required test size under design sizing, and its power there."""

    required_samples: int
    power: float


def design_required_samples(
    baseline_rate: float,
    baseline_trials: int,
    design_alternative_rate: float,
    alpha: float,
    target_power: float,
) -> DesignSizing | None:
    """The smallest ``n_t <= n_b`` from which design power stays at target.

    Scans down from ``n_b`` to the first size whose power falls short; the
    answer is the next size up. ``None`` (``BASELINE_TOO_SMALL``) when the
    power at ``n_b`` itself is short. The domain is the caller's to check
    first (:func:`check_sizing_domain`).
    """
    counts = baseline_window(baseline_trials, baseline_rate)
    cutoffs = fisher_cutoffs(counts, baseline_trials, baseline_trials, alpha)
    held: DesignSizing | None = None
    for test_samples in range(baseline_trials, 0, -1):
        if test_samples < baseline_trials:
            guess = np.rint(cutoffs * test_samples / (test_samples + 1)).astype(np.int64)
            cutoffs = _cutoffs_near(counts, baseline_trials, test_samples, alpha, guess)
        power = _fail_probability(
            cutoffs, counts, baseline_trials, baseline_rate, test_samples, design_alternative_rate
        )
        if power < target_power:
            return held
        held = DesignSizing(required_samples=test_samples, power=power)
    return held


def design_detectable_rate(
    test_samples: int,
    baseline_rate: float,
    baseline_trials: int,
    alpha: float,
    target_power: float,
) -> float | None:
    """The largest design alternative rate detectable at the target design power.

    Power falls as ``p_design`` rises toward ``p0``, so bisection over
    ``(0, p0)`` to ``1e-10``; ``None`` when even ``p_design = 0`` falls short.
    """
    counts = baseline_window(baseline_trials, baseline_rate)
    cutoffs = fisher_cutoffs(counts, baseline_trials, test_samples, alpha)

    def power_at(rate: float) -> float:
        return _fail_probability(
            cutoffs, counts, baseline_trials, baseline_rate, test_samples, rate
        )

    if power_at(0.0) < target_power:
        return None
    low, high = 0.0, baseline_rate
    while high - low > _DETECTABLE_RATE_TOLERANCE:
        mid = (low + high) / 2
        if power_at(mid) >= target_power:
            low = mid
        else:
            high = mid
    return low


def design_power_at(
    test_samples: int,
    baseline_rate: float,
    baseline_trials: int,
    design_alternative_rate: float,
    alpha: float,
) -> float:
    """The design power at a candidate test size (see ``regression.design_power``)."""
    return design_power(
        baseline_trials, test_samples, alpha, baseline_rate, design_alternative_rate
    )


@dataclass(frozen=True, slots=True)
class ResolvedSizing:
    """The required test size under resolved sizing against an observed baseline.

    Attributes:
        required_samples: The smallest ``n_t`` from which the resolved power
            stays at or above the target up to ``n_b``.
        power: The resolved power at ``required_samples``.
        first_crossing: The smallest ``n_t`` whose resolved power first
            reaches the target — reported, never the answer.
    """

    required_samples: int
    power: float
    first_crossing: int


def resolved_cutoffs(baseline_successes: int, baseline_trials: int, alpha: float) -> IntArray:
    """The cutoff against an observed baseline at every test size ``1..n_b``.

    Element ``i`` is the cutoff at ``n_t = i + 1``; each size's cutoff is
    walked from its predecessor's, one or two p-values apart.
    """
    k_b = np.array([baseline_successes], dtype=np.int64)
    cutoffs = np.empty(baseline_trials, dtype=np.int64)
    cutoff = fisher_cutoffs(k_b, baseline_trials, 1, alpha)
    cutoffs[0] = cutoff[0]
    for test_samples in range(2, baseline_trials + 1):
        cutoff = _cutoffs_near(k_b, baseline_trials, test_samples, alpha, cutoff)
        cutoffs[test_samples - 1] = cutoff[0]
    return cutoffs


def resolved_sizing(
    baseline_successes: int,
    baseline_trials: int,
    design_alternative_rate: float,
    alpha: float,
    target_power: float,
) -> ResolvedSizing | None:
    """Resolved sizing: ``None`` (``BASELINE_TOO_SMALL``) when no ``n_t <= n_b``
    reaches and holds the target. The domain is the caller's to check first."""
    cutoffs = resolved_cutoffs(baseline_successes, baseline_trials, alpha)
    sizes = np.arange(1, baseline_trials + 1)
    powers = binom.cdf(cutoffs - 1, sizes, design_alternative_rate)
    below = np.flatnonzero(powers < target_power)
    if below.size and below[-1] == baseline_trials - 1:
        return None
    start = int(below[-1]) + 1 if below.size else 0
    crossing = int(np.flatnonzero(powers >= target_power)[0])
    return ResolvedSizing(
        required_samples=start + 1,
        power=float(powers[start]),
        first_crossing=crossing + 1,
    )
