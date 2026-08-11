"""The per-iteration context a stepper decides from and a scorer consumes.

Author-facing value types: one iteration's aggregate (`IterationSummary`,
`IterationResult`) with its per-criterion failure detail, structured
evidence and gated latency, and the frozen `OptimizeContext` view (history,
best, budget) the framework hands a stepper each step.
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
class ObservedExcerpt:
    """One obtained-value exemplar: what the service returned, and how often.

    The service's own output, never contract text — the deviation *shape*
    a tuner reads to tell "wrong value" from "right value, wrapped in
    prose".
    """

    excerpt: str
    count: int
    held: bool


@dataclass(frozen=True, slots=True)
class CheckGroup:
    """Checks sharing a ``(provenance, form, path)`` signature, pooled.

    The unit of evidence a stepper reasons about. Pooling is what turns
    per-input observations into a statement about the service: nine
    input-declared equality checks that all missed the same way are one
    fact about delivery form, not nine facts about nine inputs. An
    input-declared group therefore never carries input identities — only
    how many inputs it covers.

    Attributes:
        provenance: Which declaration stated the pooled checks — the
            criterion's own (a population statement, since it judges every
            sample) or the input's (``n = 1`` each, generalising only by
            pooling).
        form: The comparison form's domain name, when known.
        path: The structural address judged, when path-addressed.
        checks: Distinct checks pooled here.
        inputs: Distinct inputs the pooled checks judged.
        expected: Distinct declared operands, excerpted and capped. Carried
            faithfully for any consumer; the ``prompt-engineer`` withholds
            it from its meta model pending the leak-policy ruling.
        passed: Trials on which the pooled checks held.
        failed: Trials on which they did not.
        skipped: Trials on which they went unevaluated.
        optional: Whether every pooled check is marked optional.
        observed: Pooled obtained-value exemplars, failing first, capped.
    """

    provenance: str
    form: str | None
    path: str | None
    checks: int
    inputs: int
    expected: tuple[str, ...]
    passed: int
    failed: int
    skipped: int
    optional: bool
    observed: tuple[ObservedExcerpt, ...]

    @property
    def trials(self) -> int:
        """Trials the pooled checks were applicable to."""
        return self.passed + self.failed + self.skipped


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    """One criterion's structured evidence over an iteration.

    The criterion's own tally is the measured unit; the groups beneath it
    are triage, carrying no interval or verdict of their own — the
    standings discipline, preserved across the stepper seam.

    Attributes:
        name: The criterion's name, as declared.
        passed: Trials on which the criterion held.
        trials: Trials it saw.
        lower_bound: The criterion's Wilson lower bound, when it is
            thresholded; ``None`` when it is characterised only. Stated so
            a stepper can see how little a small move is worth, never as a
            decision rule.
        groups: The pooled check groups, most failures first.
    """

    name: str
    passed: int
    trials: int
    lower_bound: float | None
    groups: tuple[CheckGroup, ...]

    @property
    def rate(self) -> float:
        """The criterion's observed pass rate; 0.0 with no trials."""
        return self.passed / self.trials if self.trials else 0.0


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
        evidence: Every criterion's structured evidence, in declaration
            order — the postcondition standings the run already computes,
            pooled into the shapes a stepper reasons about. Sits beside
            ``failures_by_criterion`` rather than replacing it: that
            mapping is a published seam user steppers consume.
        latency: The gated latency summary; ``None`` when no sample passed.
    """

    passes: int
    samples: int
    failures_by_criterion: Mapping[str, FailureDetail] = field(default_factory=dict)
    evidence: tuple[CriterionEvidence, ...] = ()
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
    def evidence(self) -> tuple[CriterionEvidence, ...]:
        """Every criterion's structured evidence, in declaration order."""
        return self.summary.evidence

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
