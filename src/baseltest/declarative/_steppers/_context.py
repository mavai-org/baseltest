"""The per-iteration context a stepper decides from and a scorer consumes.

Author-facing value types: one iteration's aggregate (`IterationSummary`,
`IterationResult`) with its per-criterion failure detail and gated latency,
and the frozen `OptimizeContext` view (history, best, budget) the framework
hands a stepper each step.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FailureExemplar:
    """One failing sample a criterion saw: the driving input and the reason."""

    input: Any
    reason: str


@dataclass(frozen=True, slots=True)
class FailureDetail:
    """One criterion's failures over an iteration: the count and exemplars."""

    count: int
    exemplars: tuple[FailureExemplar, ...] = ()


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """The gated latency percentiles one iteration observed, if any.

    A percentile is ``None`` when too few samples passed to state it —
    the family's minimum-contributing-samples gate, not missing data.
    """

    contributing_samples: int
    total_samples: int
    p50_ms: int | None = None
    p90_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None


@dataclass(frozen=True, slots=True)
class IterationSummary:
    """One iteration's aggregate result — what a scorer consumes.

    Attributes:
        passes: Samples on which every criterion passed.
        samples: Samples executed this iteration.
        failures_by_criterion: Per-criterion failure counts with exemplars,
            criteria that failed nothing omitted.
        latency: The gated latency summary; ``None`` when no sample passed.
    """

    passes: int
    samples: int
    failures_by_criterion: Mapping[str, FailureDetail] = field(default_factory=dict)
    latency: LatencySummary | None = None

    @property
    def pass_rate(self) -> float:
        """The observed overall pass rate; 0.0 with no samples."""
        return self.passes / self.samples if self.samples else 0.0


@dataclass(frozen=True, slots=True)
class IterationResult:
    """One completed iteration, as a stepper's history sees it."""

    config: dict[str, Any]
    score: float
    summary: IterationSummary

    @property
    def passes(self) -> int:
        """Samples on which every criterion passed."""
        return self.summary.passes

    @property
    def samples(self) -> int:
        """Samples executed this iteration."""
        return self.summary.samples

    @property
    def failures_by_criterion(self) -> Mapping[str, FailureDetail]:
        """Per-criterion failure counts with exemplars."""
        return self.summary.failures_by_criterion

    @property
    def latency(self) -> LatencySummary | None:
        """The gated latency summary; ``None`` when no sample passed."""
        return self.summary.latency


@dataclass(frozen=True, slots=True)
class OptimizeContext:
    """The frozen per-iteration view a stepper decides from.

    Attributes:
        history: Every completed iteration, oldest first.
        best: The best iteration so far, objective-aware.
        iteration: The index of the iteration the stepper is about to
            propose.
        iterations_remaining: How many more iterations the run's cap
            allows — the stepper's budget visibility.
    """

    history: tuple[IterationResult, ...]
    best: IterationResult | None
    iteration: int
    iterations_remaining: int
