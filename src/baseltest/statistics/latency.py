"""Empirical latency percentiles: the nearest-rank method.

Latency is treated non-parametrically throughout the family: no
distribution is fitted, and percentiles are read directly off the order
statistics of the observed sample. For a percentile ``p`` over ``n``
sorted observations, the estimate is the order statistic at rank
``ceil(p * n)`` (one-based, clamped to ``[1, n]``). Nearest-rank is
chosen over interpolating methods so that integer-millisecond samples
yield integer-millisecond estimates, aligning with how latency
thresholds are specified and reported.

Summary statistics (mean, maximum) accompany the percentiles for
reporting; the maximum is itself the ``p = 1.0`` order statistic.
"""

import math
from collections.abc import Sequence


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
