"""Empirical latency percentiles: the nearest-rank method, and the
order-statistic threshold derivation built on it.

Latency is treated non-parametrically throughout the family: no
distribution is fitted, and percentiles are read directly off the order
statistics of the observed sample. For a percentile ``p`` over ``n``
sorted observations, the estimate is the order statistic at rank
``ceil(p * n)`` (one-based, clamped to ``[1, n]``). Nearest-rank is
chosen over interpolating methods so that integer-millisecond samples
yield integer-millisecond estimates, aligning with how latency
thresholds are specified and reported.

Threshold derivation from a measured baseline uses the exact binomial
order-statistic upper confidence bound (Statistical Companion §12.4.2):
the threshold is the ``k``-th order statistic of the baseline where
``k`` derives from the binomial sampling distribution of quantile ranks.
The construction is distribution-free, and the derived threshold is
always an observed latency. When the derived rank exceeds the baseline
size, no finite-sample distribution-free bound exists at the requested
confidence (§12.5.2.1) — the result says so via ``saturated`` rather
than silently presenting the sample maximum as an exact bound.

Summary statistics (mean, maximum) accompany the percentiles for
reporting; the maximum is itself the ``p = 1.0`` order statistic.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scipy.stats import binom


def latency_percentile(latencies: Sequence[float], percentile: float) -> float:
    """The nearest-rank empirical percentile of a latency sample.

    Args:
        latencies: Observed durations; at least one, any order.
        percentile: The percentile level, in ``(0, 1]``.

    Returns:
        The order statistic at rank ``ceil(percentile * n)``, clamped to
        the sample.

    Raises:
        ValueError: On an empty sample (percentiles over an empty
            population are meaningless) or a percentile outside ``(0, 1]``.
    """
    if not latencies:
        raise ValueError("cannot compute a percentile of an empty latency sample")
    if not 0 < percentile <= 1:
        raise ValueError(f"percentile must be in (0, 1], got {percentile}")
    ordered = sorted(latencies)
    rank = math.ceil(percentile * len(ordered))
    rank = min(max(rank, 1), len(ordered))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class LatencyThreshold:
    """A derived one-sided upper bound on a baseline percentile.

    Attributes:
        rank: The one-based order-statistic rank the threshold was read
            at, after the companion's clamp to ``[ceil(p * n), n]``.
        threshold: The bound itself — the ``rank``-th smallest baseline
            latency, an observed value by construction.
        baseline_percentile: The nearest-rank point estimate of the
            baseline percentile, for reporting; never the threshold.
        n: The baseline sample count.
        k_raw: The unclamped binomial-derived rank. When it exceeds
            ``n`` the existence condition fails.
        saturated: ``True`` iff ``k_raw > n`` — no finite-sample
            distribution-free upper bound exists at the requested
            confidence from this baseline size, and ``threshold`` is
            merely the sample maximum, not an exact bound.
    """

    rank: int
    threshold: float
    baseline_percentile: float
    n: int
    k_raw: int
    saturated: bool


def derive_latency_threshold(
    baseline_latencies: Sequence[float], percentile: float, confidence: float
) -> LatencyThreshold:
    """The exact binomial order-statistic upper bound on a baseline percentile.

    ``k_raw = qbinom(1 - alpha, n, p) + 1``; the threshold is the
    ``max(ceil(p * n), min(k_raw, n))``-th order statistic of the sorted
    baseline (Statistical Companion §12.4.2). Callers judging against the
    bound must branch on ``saturated`` first — a saturated result is not
    an exact bound (§12.5.2.1).

    Args:
        baseline_latencies: The baseline's passing-sample latencies; at
            least one, any order.
        percentile: The percentile level, in ``(0, 1]``.
        confidence: The one-sided confidence level, in ``(0, 1)``.

    Raises:
        ValueError: On an empty baseline or out-of-range parameters.
    """
    if not baseline_latencies:
        raise ValueError("cannot derive a latency threshold from an empty baseline")
    if not 0 < percentile <= 1:
        raise ValueError(f"percentile must be in (0, 1], got {percentile}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    ordered = sorted(baseline_latencies)
    n = len(ordered)
    k_raw = int(binom.ppf(confidence, n, percentile)) + 1
    point_rank = math.ceil(percentile * n)
    rank = max(point_rank, min(k_raw, n))
    return LatencyThreshold(
        rank=rank,
        threshold=ordered[rank - 1],
        baseline_percentile=ordered[min(max(point_rank, 1), n) - 1],
        n=n,
        k_raw=k_raw,
        saturated=k_raw > n,
    )


def bound_existence_minimum(percentile: float, confidence: float) -> int:
    """The minimum baseline size for a non-saturated bound at this confidence.

    ``ceil(log(alpha) / log(p))`` — the Wilks tolerance-interval condition
    (Statistical Companion §12.5.2.1). A baseline smaller than this cannot
    support a distribution-free upper bound on the ``percentile``-quantile
    at the requested confidence, whatever its values.

    Raises:
        ValueError: On out-of-range parameters (``percentile`` must be in
            ``(0, 1)`` here — the ``p = 1`` quantile has no finite bound).
    """
    if not 0 < percentile < 1:
        raise ValueError(f"percentile must be in (0, 1), got {percentile}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    return math.ceil(math.log(1 - confidence) / math.log(percentile))


def latency_mean(latencies: Sequence[float]) -> float:
    """The sample mean of observed durations.

    Raises:
        ValueError: On an empty sample.
    """
    if not latencies:
        raise ValueError("cannot compute the mean of an empty latency sample")
    return sum(latencies) / len(latencies)


def latency_max(latencies: Sequence[float]) -> float:
    """The sample maximum — the ``p = 1.0`` order statistic.

    Raises:
        ValueError: On an empty sample.
    """
    if not latencies:
        raise ValueError("cannot compute the maximum of an empty latency sample")
    return max(latencies)
