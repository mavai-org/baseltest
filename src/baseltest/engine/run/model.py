"""The run's value model: how a contract is sampled, and what a run produces.

Pure data — the nouns the sampling loop reads and writes, plus the run
vocabulary (kind and intent). Nothing here executes a run or judges an
outcome; those behaviours live in sibling modules that import these types.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from baseltest.contract import (
    Criterion,
    CriterionTally,
    DeliveryCause,
    FailureKind,
    Outcome,
    PostconditionStanding,
)
from baseltest.statistics import (
    ComplianceVerdict,
    ConfigurationError,
    DecisionRule,
    Dimension,
    Envelopes,
    OverallVerdict,
    RegressionVerdict,
    Verdict,
    type_one_envelopes,
)
from baseltest.statistics import (
    Intent as Intent,
)

if TYPE_CHECKING:
    from ..latency import LatencyEvaluation


class RunKind(Enum):
    """The run mode, chosen at invocation: the family's verb-carries-the-posture rule."""

    TEST = "test"
    MEASURE = "measure"
    EXPLORE = "explore"
    OPTIMIZE = "optimize"


@dataclass(frozen=True, slots=True)
class RunPlan:
    """How a contract is to be sampled.

    Attributes:
        samples: Total number of invocations.
        inputs: The fixed, finite input list; invocations cycle through it.
        kind: The run mode, chosen at invocation.
        intent: Verification (an infeasible design is refused) or smoke.
        advisory: The dimensions the run makes advisory: decided and
            reported, never failing the test (§12.6). Empty, the default,
            every assertion is enforced.
    """

    samples: int
    inputs: tuple[Any, ...]
    kind: RunKind = RunKind.TEST
    intent: Intent = Intent.VERIFICATION
    advisory: frozenset[Dimension] = frozenset()

    def __post_init__(self) -> None:
        if self.samples <= 0:
            raise ValueError(f"samples must be positive, got {self.samples}")
        if not self.inputs:
            raise ValueError("inputs must be non-empty")


@dataclass(frozen=True, slots=True)
class RefusedPart:
    """One part of a configuration refused before any sample runs.

    Attributes:
        code: The configuration error.
        subject: What the part is: a criterion's name, or a latency
            constraint's percentile label (``latency p95``).
        planned_samples: The test's planned sample size.
        limit: For ``TEST_LARGER_THAN_BASELINE``, the baseline run's sample
            size; for ``COMPLIANCE_INFEASIBLE``, the smallest size at which
            a pass is possible.
        requirement: For ``COMPLIANCE_INFEASIBLE``, the requirement the
            design cannot demonstrate.
    """

    code: ConfigurationError
    subject: str
    planned_samples: int
    limit: int
    requirement: float | None = None


Decision = ComplianceVerdict | RegressionVerdict
"""A judged criterion's decision under its rule."""


@dataclass(frozen=True, slots=True)
class PowerDisclosure:
    """What a regression criterion's design can detect (§5.6, §10.2).

    Attributes:
        minimum_detectable_degradation: The smallest drop from the baseline
            rate detected with 80% power — it inverts the *design* power
            (baseline and test both yet to be drawn); ``None`` when no drop
            is detectable at that power.
        design_alternative_rate: The declared rate at which the test is to
            reach its target power, when the criterion declares one.
        design_power: The power at that rate with the baseline and the test
            both yet to be drawn, the baseline at its observed rate.
        resolved_power: The power at that rate of this test, resolved
            against the observed baseline, whose cutoff is fixed. The two
            powers answer different questions and are named apart.
    """

    minimum_detectable_degradation: float | None
    design_alternative_rate: float | None = None
    design_power: float | None = None
    resolved_power: float | None = None


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """One criterion's outcome over the whole run.

    A judged criterion carries its decision under its rule; a criterion
    without a bar is characterised only -- its ``decision`` is ``None`` and
    its rate is reported without judgement. ``lower_bound`` is the Wilson
    lower bound, a descriptive interval that decides nothing.

    ``standings`` is the criterion's descriptive per-postcondition tally —
    per ``(input, check)``, the passed/failed/skipped counts over the run —
    triage data carrying no interval, threshold, or verdict of its own.
    """

    criterion: Criterion
    tally: CriterionTally
    lower_bound: float | None
    decision: Decision | None
    standings: tuple[PostconditionStanding, ...] = ()
    power: PowerDisclosure | None = None

    @property
    def verdict(self) -> Verdict | None:
        """The criterion's verdict; ``None`` when it is characterised only."""
        return self.decision.verdict if self.decision is not None else None

    @property
    def name(self) -> str:
        """The criterion's name."""
        return self.criterion.name


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """One sample's full observation — the result projection's raw material.

    Attributes:
        input_index: Position of the driving input in the plan's input
            list (the index, not the value — the developer has the list).
        postconditions: ``(name, status)`` pairs across every criterion's
            postconditions, in evaluation order, with the three-valued
            :class:`~baseltest.contract.Outcome` status.
        execution_time_ms: Wall-clock duration of the service invocation
            only — evaluation and bookkeeping are excluded.
        content: The service's response, verbatim.
        passed: Whether every criterion passed this sample.
        failure_reasons: ``(criterion name, reason)`` pairs for the
            criteria this sample failed with a stated reason — the raw
            material of failure exemplars.
        delivery_cause: Why this sample's delivery failed, when it did.
            ``None`` on a delivered sample, whether it passed or failed —
            the field distinguishes *no response to judge* from *a
            response that was judged*, which is the one thing an empty
            ``content`` and an all-skipped outcome list cannot say on
            their own: a service may legitimately answer with nothing.
    """

    input_index: int
    postconditions: tuple[tuple[str, Outcome], ...]
    execution_time_ms: int
    content: str
    passed: bool
    failure_reasons: tuple[tuple[str, str], ...] = ()
    delivery_cause: DeliveryCause | None = None


@dataclass(frozen=True, slots=True)
class FailureAttribution:
    """One bounded failure identity and the trials attributed to it.

    Run-level and per *trial*, not per criterion: each failed trial counts
    once, against the first check that did not hold — or, where nothing was
    delivered, against the delivery cause. Summing per-criterion tallies
    instead would count a trial once per criterion it failed, which for an
    undelivered trial (it fails every criterion) multiplies one incident by
    the width of the contract.

    Computed for every run, including those that keep no per-sample
    records: a test run states its attribution without carrying payloads.
    """

    condition: str
    count: int
    kind: FailureKind


@dataclass(frozen=True, slots=True)
class RunResult:
    """Everything a run produced; consumers render or persist, never recompute.

    Attributes:
        contract_id: The contract's identity.
        kind: The run kind executed.
        plan: The plan the run executed under.
        criterion_results: Per-criterion outcomes, in declaration order.
        overall: The test's verdict ``V_test`` with the two dimensions it
            composes and what triggered a FAIL or an INCONCLUSIVE; ``None``
            for a run with nothing judged (an observation renders no
            verdict).
        started_at: Run start, UTC.
        finished_at: Run end, UTC.
        inputs_identity: Fingerprint of the input list (order-insensitive).
        samples: Per-sample records, present only when the run was asked
            to record them (explorations and measures do; tests don't
            carry per-sample payloads).
        latency: The latency dimension's outcome, when the contract
            asserts a latency bar; composed with the functional dimension
            into ``overall``.
    """

    contract_id: str
    kind: RunKind
    plan: RunPlan
    criterion_results: tuple[CriterionResult, ...]
    overall: OverallVerdict | None
    started_at: datetime
    finished_at: datetime
    inputs_identity: str
    overall_successes: int = 0
    samples: tuple[SampleRecord, ...] = ()
    # Reported token usage summed over the run's samples; 0 when no
    # service reply carried usage (cost blocks then state no tokens).
    total_tokens: int = 0
    # Per-trial first-failure attribution over the whole run, in a
    # deterministic order; empty when every trial passed.
    failure_attribution: tuple[FailureAttribution, ...] = ()
    latency: "LatencyEvaluation | None" = None

    @property
    def composite(self) -> Verdict | None:
        """The test's verdict ``V_test``; ``None`` for an observation."""
        return self.overall.verdict if self.overall is not None else None

    @property
    def envelopes(self) -> Envelopes:
        """The Type-I envelopes over every binding decision the run made, by
        direction: those of the enforced dimensions only (§1.4.6, §12.6)."""
        decisions: list[tuple[DecisionRule, float]] = []
        if Dimension.FUNCTIONAL not in self.plan.advisory:
            decisions.extend(
                (r.decision.rule, r.decision.alpha)
                for r in self.criterion_results
                if r.decision is not None
            )
        if self.latency is not None and Dimension.LATENCY not in self.plan.advisory:
            decisions.extend(
                (e.judgement.rule, e.judgement.alpha) for e in self.latency.evaluations
            )
        return type_one_envelopes(decisions)

    @property
    def observed_rate(self) -> float:
        """The run's overall observed pass rate — samples that met every
        criterion, over the planned sample count (always positive)."""
        return self.overall_successes / self.plan.samples

    @property
    def thresholded_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that received verdicts."""
        return tuple(r for r in self.criterion_results if r.verdict is not None)

    @property
    def characterised_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that are characterised, never judged."""
        return tuple(r for r in self.criterion_results if r.verdict is None)
