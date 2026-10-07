"""Latency over a run: the gated summary the artefacts share, and the judgement.

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
from enum import StrEnum
from typing import TYPE_CHECKING

from baseltest.contract import PERCENTILE_LEVELS, LatencyBar, LatencyBound
from baseltest.statistics import (
    Intent,
    LatencyJudgement,
    NondegeneracyPlanning,
    PrecedencePlanning,
    Verdict,
    judge_latency_constraint,
    latency_percentile,
    plan_nondegeneracy,
    plan_precedence,
    structural_composite,
)
from baseltest.statistics import minimum_contributing_samples as _minimum_for_level


class LatencyBasis(StrEnum):
    """Which population a latency summary's durations were drawn from.

    Latency is conditioned on functional success throughout the family, so
    the only basis is the passing samples.
    """

    PASSING_SAMPLES = "passing-samples"


if TYPE_CHECKING:  # a type-only edge: the run module imports this one at runtime
    from .run import SampleRecord

# The family's per-percentile minimum-contributing-samples rule (the
# Statistical Companion's non-degeneracy gate): below the minimum the
# percentile is omitted from the artefact entirely rather than carrying a
# number that looks authoritative but is noise. The minimums are the
# statistics core's, conformance-locked to the mavai-R
# latency_percentile_minimums fixture.
_PERCENTILES: tuple[tuple[str, float, int], ...] = tuple(
    (f"{label}Ms", level, _minimum_for_level(level)) for label, level in PERCENTILE_LEVELS.items()
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
        basis: The :class:`LatencyBasis` naming which samples contributed.
    """

    contributing_samples: int
    total_samples: int
    percentiles: tuple[tuple[str, int], ...]
    sorted_passing_latencies_ms: tuple[int, ...] = ()
    basis: LatencyBasis = LatencyBasis.PASSING_SAMPLES


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
    """One asserted latency constraint's outcome over a run.

    Attributes:
        bound: The constraint as asserted.
        judgement: The statistics core's judgement: the rule that decided,
            its decision artefact (``y_min`` and the within-threshold count
            for an explicit requirement; the rank, the derived threshold and
            the test's percentile, or saturation, for a baseline-derived
            one) and the verdict.
    """

    bound: LatencyBound
    judgement: LatencyJudgement

    @property
    def verdict(self) -> Verdict:
        """The constraint's verdict under its rule."""
        return self.judgement.verdict


@dataclass(frozen=True, slots=True)
class LatencyEvaluation:
    """The latency dimension's outcome: observed percentiles and per-constraint judgements.

    Attributes:
        bar: The contract's latency bar as asserted.
        contributing_samples: Passing samples, whose durations were judged.
        total_samples: All samples in the run.
        observed: The gated observed percentiles (``(label, ms)`` for every
            supported percentile the contributing count can estimate) —
            descriptive context, independent of which were asserted.
        evaluations: One outcome per asserted constraint, in tail order.
    """

    bar: LatencyBar
    contributing_samples: int
    total_samples: int
    observed: tuple[tuple[str, int], ...]
    evaluations: tuple[BoundEvaluation, ...]

    @property
    def verdict(self) -> Verdict:
        """``V_latency``: the structural composite of the constraints, whether
        the dimension is enforced or advisory."""
        return structural_composite(evaluation.verdict for evaluation in self.evaluations)


def evaluate_latency(
    bar: LatencyBar, passing_durations_ms: Sequence[int], total_samples: int, intent: Intent
) -> LatencyEvaluation:
    """Judge a latency bar against a run's passing-sample durations.

    Latency is conditioned on functional success (only passing samples'
    durations are judged). Each constraint is decided after the run on the
    actual number of successful latencies, by the rule for its threshold
    source (see ``statistics.judge_latency_constraint``).
    """
    contributing = sorted(passing_durations_ms)
    observed = tuple(
        (key.removesuffix("Ms"), round(latency_percentile(contributing, level)))
        for key, level, minimum in _PERCENTILES
        if len(contributing) >= minimum
    )
    baseline = bar.baseline.sorted_latencies_ms if bar.baseline is not None else ()
    evaluations = tuple(
        BoundEvaluation(
            bound=bound,
            judgement=judge_latency_constraint(
                contributing,
                bound.level,
                bar.alpha,
                source=bar.origin,
                intent=intent,
                threshold_ms=bound.threshold_ms,
                baseline_latencies=baseline,
            ),
        )
        for bound in bar.bounds
    )
    return LatencyEvaluation(
        bar=bar,
        contributing_samples=len(contributing),
        total_samples=total_samples,
        observed=observed,
        evaluations=evaluations,
    )


@dataclass(frozen=True, slots=True)
class LatencyPlanning:
    """The pre-run planning checks of one baseline-derived constraint (§12.5.3).

    Warnings and planning figures on the *expected* number of successful
    latencies — never a refusal and never a verdict: both decisions are
    made after the run on the actual count.
    """

    bound: LatencyBound
    nondegeneracy: NondegeneracyPlanning
    precedence: PrecedencePlanning

    @property
    def warns(self) -> bool:
        """Whether either check falls short at the expected count."""
        return self.nondegeneracy.warning or self.precedence.warning


def plan_latency(bar: LatencyBar, planned_samples: int) -> tuple[LatencyPlanning, ...]:
    """The planning checks for each baseline-derived constraint; none for explicit ones.

    An explicit requirement's only pre-run check is its exact-binomial
    feasibility, a configuration error judged in preflight.
    """
    if bar.baseline is None:
        return ()
    rate = bar.baseline.passing_rate
    return tuple(
        LatencyPlanning(
            bound=bound,
            nondegeneracy=plan_nondegeneracy(bound.level, planned_samples, rate),
            precedence=plan_precedence(
                len(bar.baseline.sorted_latencies_ms), planned_samples, rate, bound.level, bar.alpha
            ),
        )
        for bound in bar.bounds
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
