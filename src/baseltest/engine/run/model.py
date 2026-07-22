"""The run's value model: how a contract is sampled, and what a run produces.

Pure data — the nouns the sampling loop reads and writes, plus the run
vocabulary (kind and intent). Nothing here executes a run or judges an
outcome; those behaviours live in sibling modules that import these types.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from baseltest.contract import Criterion, CriterionTally, Outcome
from baseltest.statistics.verdict import Verdict

if TYPE_CHECKING:
    from ..latency import LatencyEvaluation


class RunKind(Enum):
    """The run mode, chosen at invocation: the family's verb-carries-the-posture rule."""

    TEST = "test"
    MEASURE = "measure"
    EXPLORE = "explore"
    OPTIMIZE = "optimize"


class Intent(Enum):
    """Whether the run's statistical adequacy is enforced or advisory."""

    VERIFICATION = "verification"
    SMOKE = "smoke"


@dataclass(frozen=True, slots=True)
class RunPlan:
    """How a contract is to be sampled.

    Attributes:
        samples: Total number of invocations.
        inputs: The fixed, finite input list; invocations cycle through it.
        kind: The run mode, chosen at invocation.
        intent: Verification (feasibility enforced) or smoke (advisory).
    """

    samples: int
    inputs: tuple[Any, ...]
    kind: RunKind = RunKind.TEST
    intent: Intent = Intent.VERIFICATION

    def __post_init__(self) -> None:
        if self.samples <= 0:
            raise ValueError(f"samples must be positive, got {self.samples}")
        if not self.inputs:
            raise ValueError("inputs must be non-empty")


@dataclass(frozen=True, slots=True)
class InfeasibleCriterion:
    """One criterion whose threshold the planned sample count cannot support."""

    name: str
    threshold: float
    confidence: float
    minimum_samples: int


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """One criterion's outcome over the whole run.

    A thresholded criterion carries a verdict and its Wilson lower bound;
    an unthresholded criterion is characterised only -- its ``verdict`` and
    ``lower_bound`` are ``None`` and its rate is reported without judgement.
    """

    criterion: Criterion
    tally: CriterionTally
    lower_bound: float | None
    verdict: Verdict | None

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
    """

    input_index: int
    postconditions: tuple[tuple[str, Outcome], ...]
    execution_time_ms: int
    content: str
    passed: bool
    failure_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    """Everything a run produced; consumers render or persist, never recompute.

    Attributes:
        contract_id: The contract's identity.
        kind: The run kind executed.
        plan: The plan the run executed under.
        criterion_results: Per-criterion outcomes, in declaration order.
        composite: The run-level verdict -- FAIL if any thresholded
            criterion failed, PASS otherwise; ``None`` for a run with no
            thresholded criteria (an observation renders no verdict).
        started_at: Run start, UTC.
        finished_at: Run end, UTC.
        inputs_identity: Fingerprint of the input list (order-insensitive).
        samples: Per-sample records, present only when the run was asked
            to record them (explorations and measures do; tests don't
            carry per-sample payloads).
        latency: The latency dimension's outcome, when the contract
            asserts a latency bar; folded into the composite by
            conjunction.
    """

    contract_id: str
    kind: RunKind
    plan: RunPlan
    criterion_results: tuple[CriterionResult, ...]
    composite: Verdict | None
    started_at: datetime
    finished_at: datetime
    inputs_identity: str
    overall_successes: int = 0
    samples: tuple[SampleRecord, ...] = ()
    latency: "LatencyEvaluation | None" = None

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
