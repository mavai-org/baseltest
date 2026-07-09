"""Run execution: preflight, sampling loop, verdicts, composite."""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from baseltest.contract import (
    Criterion,
    CriterionTally,
    ServiceContract,
    TrialViews,
    evaluate_trial,
)
from baseltest.statistics import check_feasibility
from baseltest.statistics.verdict import Verdict
from baseltest.statistics.wilson import wilson_lower_bound

from .latency import evaluate_latency

if TYPE_CHECKING:
    from .latency import LatencyEvaluation


class RunKind(Enum):
    """The run mode, chosen at invocation: the family's verb-carries-the-posture rule."""

    TEST = "test"
    MEASURE = "measure"
    EXPLORE = "explore"


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
        kind: The run mode (test or measure), chosen at invocation.
        intent: Verification (feasibility enforced) or smoke (advisory).
    """

    samples: int
    inputs: tuple[str, ...]
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


class InfeasibleRunError(Exception):
    """The declared sample count cannot support every declared threshold.

    Raised before any invocation, under verification intent only. Carries
    the per-criterion detail so the caller can render a constructive,
    format-vocabulary refusal (never this exception's bare text).
    """

    def __init__(self, samples: int, infeasible: Sequence[InfeasibleCriterion]) -> None:
        self.samples = samples
        self.infeasible = tuple(infeasible)
        self.governing_minimum = max(c.minimum_samples for c in self.infeasible)
        names = ", ".join(c.name for c in self.infeasible)
        super().__init__(
            f"{samples} samples cannot support the declared threshold(s) of: {names}; "
            f"minimum feasible samples: {self.governing_minimum}"
        )


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
            postconditions, in evaluation order; status is ``passed``,
            ``failed``, or ``skipped``.
        execution_time_ms: Wall-clock duration of the service invocation
            only — evaluation and bookkeeping are excluded.
        content: The service's response, verbatim.
        passed: Whether every criterion passed this sample.
    """

    input_index: int
    postconditions: tuple[tuple[str, str], ...]
    execution_time_ms: int
    content: str
    passed: bool


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
    def thresholded_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that received verdicts."""
        return tuple(r for r in self.criterion_results if r.verdict is not None)

    @property
    def characterised_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that are characterised, never judged."""
        return tuple(r for r in self.criterion_results if r.verdict is None)


def inputs_fingerprint(inputs: Sequence[str]) -> str:
    """A stable, order-insensitive fingerprint of an input list."""
    canonical = json.dumps(sorted(inputs), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_minimum_samples(contract: ServiceContract) -> int:
    """The smallest sample count supporting every declared threshold.

    Per-criterion, the minimum feasible sample size at that criterion's
    threshold and confidence; the governing minimum is the largest, since
    every criterion is evaluated over the same samples.

    Raises:
        ValueError: If the contract declares no thresholded criterion (an
            observation has no feasibility anchor to derive a size from).
    """
    thresholded = contract.thresholded_criteria
    if not thresholded:
        raise ValueError("cannot derive a sample count: no criterion declares a threshold")
    return max(
        check_feasibility(1, c.threshold, c.confidence).minimum_samples
        for c in thresholded
        if c.threshold is not None
    )


def _preflight(contract: ServiceContract, plan: RunPlan) -> None:
    """Refuse an infeasible verification test before any invocation.

    Only a test is refused: feasibility guards verdicts, and a measure run
    renders none -- an unsupportable bar is recorded as such instead.
    """
    if plan.kind is not RunKind.TEST:
        return
    infeasible = [
        InfeasibleCriterion(
            name=c.name,
            threshold=c.threshold,
            confidence=c.confidence,
            minimum_samples=check.minimum_samples,
        )
        for c in contract.thresholded_criteria
        if c.threshold is not None
        and not (check := check_feasibility(plan.samples, c.threshold, c.confidence)).feasible
    ]
    if infeasible and plan.intent is Intent.VERIFICATION:
        raise InfeasibleRunError(plan.samples, infeasible)


def _judge(criterion: Criterion, tally: CriterionTally) -> tuple[float | None, Verdict | None]:
    """A thresholded criterion's bound and verdict; (None, None) otherwise."""
    if criterion.threshold is None or tally.trials == 0:
        return None, None
    bound = wilson_lower_bound(tally.successes, tally.trials, criterion.confidence)
    verdict = Verdict.PASS if bound >= criterion.threshold else Verdict.FAIL
    return bound, verdict


def bar_standing(result: "CriterionResult") -> str:
    """The recorded standing of a declared bar: ``met``, ``not met``, or
    ``unsupportable`` when even a perfect run of this size could not have
    supported the bar — the family's three-way experiment-time judgement."""
    criterion = result.criterion
    if criterion.threshold is None:
        raise ValueError(f"criterion {criterion.name!r} declares no bar")
    if result.verdict is Verdict.PASS:
        return "met"
    trials = result.tally.trials
    best_possible = wilson_lower_bound(trials, trials, criterion.confidence)
    if best_possible < criterion.threshold:
        return "unsupportable"
    return "not met"


def execute(
    contract: ServiceContract,
    plan: RunPlan,
    on_sample: Callable[[int, int], None] | None = None,
    record_samples: bool = False,
) -> RunResult:
    """Run the plan: preflight, sample, judge, compose.

    Invocations cycle through the plan's inputs. An exception from the
    contract's invocation is a defect and aborts the run; anticipated bad
    responses are returned by the invocation and judged by the criteria.
    ``on_sample(completed, total)`` — when given — is called after each
    sample purely for progress display; it observes the loop and can never
    alter it. With ``record_samples``, every sample's full observation
    (input index, per-postcondition outcomes, invocation duration,
    response content) lands on the result — the raw material of the
    exploration artefacts' result projections.
    """
    _preflight(contract, plan)
    started_at = datetime.now(tz=UTC)
    tallies = {criterion.name: CriterionTally() for criterion in contract.criteria}
    overall_successes = 0
    sample_records: list[SampleRecord] = []
    passing_durations_ms: list[int] = []
    for i in range(plan.samples):
        input_index = i % len(plan.inputs)
        invoked_at = time.perf_counter()
        response = contract.invoke(plan.inputs[input_index])
        duration_ms = round((time.perf_counter() - invoked_at) * 1000)
        views = TrialViews(response, contract.views)  # one cache per trial, all criteria
        trial_passed = True
        outcomes: list[tuple[str, str]] = []
        for criterion in contract.criteria:
            evaluation = evaluate_trial(criterion, views)
            tallies[criterion.name].record(evaluation)
            trial_passed = trial_passed and evaluation.passed
            outcomes.extend(evaluation.outcomes)
        overall_successes += int(trial_passed)
        if trial_passed:
            passing_durations_ms.append(duration_ms)
        if record_samples:
            sample_records.append(
                SampleRecord(
                    input_index=input_index,
                    postconditions=tuple(outcomes),
                    execution_time_ms=duration_ms,
                    content=response,
                    passed=trial_passed,
                )
            )
        if on_sample is not None:
            on_sample(i + 1, plan.samples)
    finished_at = datetime.now(tz=UTC)

    results = []
    for criterion in contract.criteria:
        tally = tallies[criterion.name]
        bound, verdict = _judge(criterion, tally)
        results.append(
            CriterionResult(criterion=criterion, tally=tally, lower_bound=bound, verdict=verdict)
        )
    latency_evaluation = None
    if contract.latency is not None:
        latency_evaluation = evaluate_latency(contract.latency, passing_durations_ms, plan.samples)

    verdicts = [r.verdict for r in results if r.verdict is not None]
    if latency_evaluation is not None:
        verdicts.append(latency_evaluation.verdict)
    composite = None
    if verdicts:
        # Conjunction across dimensions: any FAIL fails; an unjudgeable
        # latency bound (INCONCLUSIVE) never counts as a pass.
        if Verdict.FAIL in verdicts:
            composite = Verdict.FAIL
        elif Verdict.INCONCLUSIVE in verdicts:
            composite = Verdict.INCONCLUSIVE
        else:
            composite = Verdict.PASS

    return RunResult(
        contract_id=contract.contract_id,
        kind=plan.kind,
        plan=plan,
        criterion_results=tuple(results),
        composite=composite,
        started_at=started_at,
        latency=latency_evaluation,
        finished_at=finished_at,
        inputs_identity=inputs_fingerprint(plan.inputs),
        overall_successes=overall_successes,
        samples=tuple(sample_records),
    )
