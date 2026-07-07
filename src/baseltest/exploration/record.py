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

from baseltest.engine import RunResult


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
        )
