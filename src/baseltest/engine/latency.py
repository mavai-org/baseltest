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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from baseltest.contract import PERCENTILE_LEVELS, LatencyBar, LatencyBound
from baseltest.statistics import latency_percentile
from baseltest.statistics.verdict import Verdict

if TYPE_CHECKING:  # a type-only edge: the run module imports this one at runtime
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


def minimum_contributing_samples(percentile: str) -> int:
    """The emission/evaluation minimum for a percentile label (``"p50"``…).

    The one gating table, shared by the artefact writers and the latency
    evaluation, conformance-locked to the published family standard.

    Raises:
        ValueError: On an unsupported label.
    """
    for key, _, minimum in _PERCENTILES:
        if key == f"{percentile}Ms":
            return minimum
    raise ValueError(f"unknown percentile {percentile!r}")


@dataclass(frozen=True, slots=True)
class BoundEvaluation:
    """One asserted latency bound's outcome over a run.

    Attributes:
        bound: The bound as asserted (with its derivation facts, for a
            baseline-derived bound).
        observed_ms: The observed nearest-rank percentile over passing
            samples, or ``None`` when too few samples passed to estimate
            this percentile at all.
        status: ``"pass"`` (observed at or below the bound), ``"fail"``
            (observed above it), or ``"infeasible"`` (not enough passing
            samples to estimate the percentile — no judgement possible).
        reason: For an infeasible outcome, the plain-language why.
    """

    bound: LatencyBound
    observed_ms: int | None
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LatencyEvaluation:
    """The latency dimension's outcome: observed percentiles and per-bound judgements.

    Attributes:
        bar: The contract's latency bar as asserted.
        contributing_samples: Passing samples, whose durations were judged.
        total_samples: All samples in the run.
        observed: The gated observed percentiles (``(label, ms)`` for every
            supported percentile the contributing count can estimate) —
            descriptive context, independent of which were asserted.
        evaluations: One outcome per asserted bound, in tail order.
    """

    bar: LatencyBar
    contributing_samples: int
    total_samples: int
    observed: tuple[tuple[str, int], ...]
    evaluations: tuple[BoundEvaluation, ...]

    @property
    def verdict(self) -> Verdict:
        """FAIL if any bound is breached; INCONCLUSIVE if any could not be
        judged; PASS when every asserted bound held."""
        statuses = {evaluation.status for evaluation in self.evaluations}
        if "fail" in statuses:
            return Verdict.FAIL
        if "infeasible" in statuses:
            return Verdict.INCONCLUSIVE
        return Verdict.PASS


def evaluate_latency(
    bar: LatencyBar, passing_durations_ms: Sequence[int], total_samples: int
) -> LatencyEvaluation:
    """Judge a latency bar against a run's passing-sample durations.

    Latency is conditioned on functional success (only passing samples'
    durations are judged), the estimator is the nearest-rank percentile,
    and a bound passes iff ``observed <= threshold`` — one-sided, equality
    passes. A percentile whose minimum-contributing-samples rule is unmet
    by the run yields an infeasible outcome rather than a judgement.
    """
    contributing = sorted(passing_durations_ms)
    observed = tuple(
        (key.removesuffix("Ms"), round(latency_percentile(contributing, level)))
        for key, level, minimum in _PERCENTILES
        if len(contributing) >= minimum
    )
    evaluations = []
    for bound in bar.bounds:
        minimum = minimum_contributing_samples(bound.percentile)
        if len(contributing) < minimum:
            evaluations.append(
                BoundEvaluation(
                    bound=bound,
                    observed_ms=None,
                    status="infeasible",
                    reason=(
                        f"{bound.percentile} needs at least {minimum} passing samples "
                        f"to estimate; this run had {len(contributing)} of "
                        f"{total_samples}"
                    ),
                )
            )
            continue
        observed_ms = round(latency_percentile(contributing, PERCENTILE_LEVELS[bound.percentile]))
        evaluations.append(
            BoundEvaluation(
                bound=bound,
                observed_ms=observed_ms,
                status="pass" if observed_ms <= bound.threshold_ms else "fail",
            )
        )
    return LatencyEvaluation(
        bar=bar,
        contributing_samples=len(contributing),
        total_samples=total_samples,
        observed=observed,
        evaluations=tuple(evaluations),
    )


def latency_block(samples: "tuple[SampleRecord, ...]") -> LatencyBlock | None:
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
