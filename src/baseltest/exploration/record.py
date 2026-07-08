"""The exploration record: what one explored configuration's run observed.

Deliberately descriptive: rates, counts, and failure reasons — never a
bound, a threshold, or a verdict. Triage over precision is the point of an
exploration; judgement belongs to tests.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from baseltest.engine import RunResult, SampleRecord
from baseltest.statistics import latency_percentile

# The family's per-percentile minimum-contributing-samples rule: percentile
# p needs at least 1 / (1 - p) contributing samples; below the minimum the
# percentile is omitted from the artefact entirely rather than carrying a
# number that looks authoritative but is noise.
_PERCENTILES: tuple[tuple[str, float, int], ...] = (
    ("p50Ms", 0.50, 1),
    ("p90Ms", 0.90, 10),
    ("p95Ms", 0.95, 20),
    ("p99Ms", 0.99, 100),
)


@dataclass(frozen=True, slots=True)
class LatencyBlock:
    """The gated aggregate-latency summary over one configuration's samples.

    Only samples that passed contribute durations — timing of incorrect
    behaviour does not characterise the latency of the correct path. The
    population-indicator triple (basis, contributing, total) lets a reader
    verify which percentiles can be present.
    """

    contributing_samples: int
    total_samples: int
    percentiles: tuple[tuple[str, int], ...]
    basis: str = "passing-samples"


def _latency_block(samples: tuple[SampleRecord, ...]) -> LatencyBlock | None:
    contributing = [s.execution_time_ms for s in samples if s.passed]
    if not contributing:
        return None  # no percentile distribution over an empty population
    percentiles = tuple(
        (key, round(latency_percentile(contributing, level)))
        for key, level, minimum in _PERCENTILES
        if len(contributing) >= minimum
    )
    return LatencyBlock(
        contributing_samples=len(contributing),
        total_samples=len(samples),
        percentiles=percentiles,
    )


@dataclass(frozen=True, slots=True)
class CriterionStatistics:
    """One criterion's descriptive counts over a configuration's samples."""

    passes: int
    fails: int

    @property
    def observed_rate(self) -> float:
        """The observed pass rate; 0.0 with no trials."""
        trials = self.passes + self.fails
        return self.passes / trials if trials else 0.0


@dataclass(frozen=True, slots=True)
class ExplorationRecord:
    """Everything one configuration's exploration artefact states.

    Attributes:
        contract_id: The explored contract's identity.
        generated_at: When this configuration's run finished, UTC.
        factors: The configuration's discriminating factor values — the
            grid keys that vary, with this point's resolved values, in
            canonical order. Empty when the grid has a single point.
        samples_planned: The per-configuration sample count asked for.
        samples_executed: The samples actually run.
        successes: Trials on which every criterion passed.
        failure_distribution: Failure reasons and counts, aggregated over
            all criteria; empty when every trial passed everything.
        criteria: Per-criterion descriptive counts, in declaration order.
        total_time_ms: Wall-clock duration of this configuration's run.
        latency: The gated aggregate-latency summary; ``None`` when no
            sample passed (or no per-sample records exist).
        samples: Per-sample records — the result projection's content.
    """

    contract_id: str
    generated_at: datetime
    factors: tuple[tuple[str, Any], ...]
    samples_planned: int
    samples_executed: int
    successes: int
    failure_distribution: Mapping[str, int] = field(default_factory=dict)
    criteria: Mapping[str, CriterionStatistics] = field(default_factory=dict)
    total_time_ms: int = 0
    latency: LatencyBlock | None = None
    samples: tuple[SampleRecord, ...] = ()

    @property
    def observed_rate(self) -> float:
        """The aggregate observed pass rate; 0.0 with no samples."""
        return self.successes / self.samples_executed if self.samples_executed else 0.0

    @staticmethod
    def from_run_result(
        result: RunResult, factors: Mapping[str, Any] | None = None
    ) -> "ExplorationRecord":
        """Build one configuration's record from its completed run."""
        distribution: Counter[str] = Counter()
        criteria: dict[str, CriterionStatistics] = {}
        for criterion_result in result.criterion_results:
            tally = criterion_result.tally
            distribution.update(tally.failure_reasons)
            criteria[criterion_result.name] = CriterionStatistics(
                passes=tally.successes, fails=tally.trials - tally.successes
            )
        elapsed = (result.finished_at - result.started_at).total_seconds()
        return ExplorationRecord(
            contract_id=result.contract_id,
            generated_at=result.finished_at,
            factors=tuple((factors or {}).items()),
            samples_planned=result.plan.samples,
            samples_executed=result.plan.samples,
            successes=result.overall_successes,
            failure_distribution=dict(distribution),
            criteria=criteria,
            total_time_ms=round(elapsed * 1000),
            latency=_latency_block(result.samples),
            samples=result.samples,
        )
