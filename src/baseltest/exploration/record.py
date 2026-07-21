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

from baseltest.engine import LatencyBlock, RunResult, SampleRecord, latency_block
from baseltest.engine.naming import bounded_excerpt, bounded_key, per_input_index

_DELIVERY_FAILURE_CONDITION = "service delivery failed"


@dataclass(frozen=True, slots=True)
class FailureEntry:
    """One failure-distribution entry: a bounded condition identity and its count.

    Attributes:
        condition: The violating condition's bounded identity, as the
            contract declares it — never embedding input or response
            content. A per-input condition carries its input's position
            in the name (``… (input 2)``); the position also travels
            structurally in ``input_index``.
        count: Failed trials attributed to this entry — each failed
            trial to its first failing condition, so counts sum to the
            enclosing failure total.
        input_index: The driving input's position in the input list,
            when the condition is per-input.
        input_excerpt: A bounded excerpt of the driving input, for
            human orientation only.
    """

    condition: str
    count: int
    input_index: int | None = None
    input_excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class CriterionStatistics:
    """One criterion's descriptive counts over a configuration's samples."""

    passes: int
    fails: int

    @property
    def observed_rate(self) -> float:
        """The observed pass rate. A recorded criterion has at least one
        trial (a pass or a fail)."""
        return self.passes / (self.passes + self.fails)


@dataclass(frozen=True, slots=True)
class ExplorationRecord:
    """Everything one configuration's exploration artefact states.

    Attributes:
        contract_id: The explored contract's identity.
        generated_at: When this configuration's run finished, UTC.
        factors: The configuration's discriminating factor values — the
            grid keys that vary, with this point's resolved values, in
            canonical order. Empty when the grid has a single point; names
            the artefact's file.
        configuration: The full resolved configuration the point ran
            under, constants included — what the artefact's ``factors:``
            block records. Falls back to ``factors`` when empty.
        samples_planned: The per-configuration sample count asked for.
        samples_executed: The samples actually run.
        successes: Trials on which every criterion passed.
        failure_distribution: Failure entries in deterministic order,
            each failed trial attributed to its first failing condition;
            empty when every trial passed everything.
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
    failure_distribution: tuple[FailureEntry, ...] = ()
    criteria: Mapping[str, CriterionStatistics] = field(default_factory=dict)
    total_time_ms: int = 0
    configuration: tuple[tuple[str, Any], ...] = ()
    latency: LatencyBlock | None = None
    samples: tuple[SampleRecord, ...] = ()

    @property
    def observed_rate(self) -> float:
        """The aggregate observed pass rate. A recorded exploration executed
        at least one sample."""
        return self.successes / self.samples_executed

    @staticmethod
    def from_run_result(
        result: RunResult,
        factors: Mapping[str, Any] | None = None,
        configuration: Mapping[str, Any] | None = None,
    ) -> "ExplorationRecord":
        """Build one configuration's record from its completed run."""
        criteria: dict[str, CriterionStatistics] = {}
        for criterion_result in result.criterion_results:
            tally = criterion_result.tally
            criteria[criterion_result.name] = CriterionStatistics(
                passes=tally.successes, fails=tally.trials - tally.successes
            )
        elapsed = (result.finished_at - result.started_at).total_seconds()
        return ExplorationRecord(
            contract_id=result.contract_id,
            generated_at=result.finished_at,
            factors=tuple((factors or {}).items()),
            configuration=tuple((configuration or {}).items()),
            samples_planned=result.plan.samples,
            samples_executed=result.plan.samples,
            successes=result.overall_successes,
            failure_distribution=_failure_entries(result),
            criteria=criteria,
            total_time_ms=round(elapsed * 1000),
            latency=latency_block(result.samples),
            samples=result.samples,
        )


def _failure_entries(result: RunResult) -> tuple[FailureEntry, ...]:
    """First-failure attribution over the per-sample records.

    Each failed sample contributes one count, to the first postcondition
    that failed it (a delivery failure, which fails a sample with every
    postcondition skipped, is attributed to its own stable identity), so
    the entries' counts sum to the run's failure total. When the run
    recorded no samples, falls back to the per-criterion reason tallies —
    descriptive still, but per-criterion counts, not per-trial.
    """
    if result.samples:
        counts: Counter[tuple[str, int | None]] = Counter()
        for sample in result.samples:
            if sample.passed:
                continue
            condition = next(
                (name for name, status in sample.postconditions if status == "failed"),
                _DELIVERY_FAILURE_CONDITION,
            )
            input_index = per_input_index(condition)
            counts[(bounded_key(condition), input_index)] += 1
        inputs = result.plan.inputs
        entries = [
            FailureEntry(
                condition=condition,
                count=count,
                input_index=input_index,
                input_excerpt=(
                    bounded_excerpt(str(inputs[input_index]))
                    if input_index is not None and input_index < len(inputs)
                    else None
                ),
            )
            for (condition, input_index), count in counts.items()
        ]
    else:
        distribution: Counter[str] = Counter()
        for criterion_result in result.criterion_results:
            distribution.update(criterion_result.tally.failure_reasons)
        entries = [
            FailureEntry(condition=bounded_key(reason), count=count)
            for reason, count in distribution.items()
        ]
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.condition,
                entry.input_index if entry.input_index is not None else -1,
            ),
        )
    )
