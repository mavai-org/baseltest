"""The gated aggregate-latency summary shared by the experiment artefacts.

Latency is conditioned on success throughout the family: only samples that
passed contribute durations, because the timing of incorrect behaviour does
not characterise the latency of the correct path. The summary carries the
population-indicator triple (basis, contributing, total), the percentiles
its contributing-sample count can support, and the full ascending vector
of passing-sample durations — the raw material a later consumer needs to
derive bounds at its own sample size and confidence, which is why the
vector rather than any derived value is what the artefacts persist.
"""

from dataclasses import dataclass

from baseltest.statistics import latency_percentile

from .run import SampleRecord

# The family's per-percentile minimum-contributing-samples rule (the
# Statistical Companion's non-degeneracy gate): below the minimum the
# percentile is omitted from the artefact entirely rather than carrying a
# number that looks authoritative but is noise. The values are
# conformance-locked to the mavai-R latency_percentile_minimums fixture.
_PERCENTILES: tuple[tuple[str, float, int], ...] = (
    ("p50Ms", 0.50, 5),
    ("p90Ms", 0.90, 10),
    ("p95Ms", 0.95, 20),
    ("p99Ms", 0.99, 100),
)


@dataclass(frozen=True, slots=True)
class LatencyBlock:
    """The gated aggregate-latency summary over one run's samples.

    Only samples that passed contribute durations. The population-indicator
    triple (basis, contributing, total) lets a reader verify which
    percentiles can be present.

    Attributes:
        contributing_samples: Passing samples, whose durations contribute.
        total_samples: All samples in the run.
        percentiles: ``(key, milliseconds)`` pairs, only for percentiles
            whose minimum-contributing-samples rule is met.
        sorted_passing_latencies_ms: Every contributing duration in
            milliseconds, ascending — length ``contributing_samples`` when
            built from a run.
        basis: The population token naming which samples contributed.
    """

    contributing_samples: int
    total_samples: int
    percentiles: tuple[tuple[str, int], ...]
    sorted_passing_latencies_ms: tuple[int, ...] = ()
    basis: str = "passing-samples"


def latency_block(samples: tuple[SampleRecord, ...]) -> LatencyBlock | None:
    """Build the summary from a run's samples; ``None`` when none passed.

    No percentile distribution is meaningful over an empty population —
    the absence of the block is the correct signal.
    """
    contributing = sorted(s.execution_time_ms for s in samples if s.passed)
    if not contributing:
        return None
    percentiles = tuple(
        (key, round(latency_percentile(contributing, level)))
        for key, level, minimum in _PERCENTILES
        if len(contributing) >= minimum
    )
    return LatencyBlock(
        contributing_samples=len(contributing),
        total_samples=len(samples),
        percentiles=percentiles,
        sorted_passing_latencies_ms=tuple(contributing),
    )
