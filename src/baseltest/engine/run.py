"""Run execution: preflight, sampling loop, verdicts, composite."""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any

from baseltest.contract import (
    BaseltestError,
    Criterion,
    CriterionTally,
    Outcome,
    ServiceContract,
    ServiceDeliveryError,
    TrialDefectError,
    TrialEvaluation,
    TrialViews,
    evaluate_trial,
)
from baseltest.statistics import check_feasibility
from baseltest.statistics.verdict import Verdict, evaluate_regression
from baseltest.statistics.wilson import wilson_lower_bound

from .defect import DefectDiagnosisError
from .latency import evaluate_latency
from .naming import bounded_excerpt

if TYPE_CHECKING:
    from .latency import LatencyEvaluation


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
        kind: The run mode (test or measure), chosen at invocation.
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


class InfeasibleRunError(BaseltestError):
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
    def thresholded_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that received verdicts."""
        return tuple(r for r in self.criterion_results if r.verdict is not None)

    @property
    def characterised_results(self) -> tuple[CriterionResult, ...]:
        """Results for the criteria that are characterised, never judged."""
        return tuple(r for r in self.criterion_results if r.verdict is None)


def inputs_fingerprint(inputs: Sequence[Any]) -> str:
    """A stable, order-insensitive fingerprint of an input list.

    All-string lists keep their historical canonical form, so existing
    baselines stay addressable; mixed or structured inputs canonicalise
    each entry as JSON before sorting.
    """
    if all(isinstance(entry, str) for entry in inputs):
        canonical = json.dumps(sorted(inputs), ensure_ascii=False)
    else:
        encoded = sorted(
            json.dumps(list(e) if isinstance(e, tuple) else e, ensure_ascii=False) for e in inputs
        )
        # An object wrapper, so a structured corpus can never collide with
        # the historical all-string array form.
        canonical = json.dumps({"typed-inputs": encoded}, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_minimum_samples(contract: ServiceContract[Any]) -> int:
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


def _preflight(contract: ServiceContract[Any], plan: RunPlan) -> None:
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


def _skipped_outcomes(criterion: Criterion) -> tuple[tuple[str, Outcome], ...]:
    return tuple((p.name, Outcome.SKIPPED) for p in criterion.postconditions)


def _record_failed_delivery(
    contract: ServiceContract[Any], tallies: dict[str, CriterionTally], reason: str
) -> None:
    """Count one undelivered sample as a failure of every criterion."""
    for criterion in contract.criteria:
        tallies[criterion.name].record(
            TrialEvaluation(passed=False, reason=reason, outcomes=_skipped_outcomes(criterion))
        )


def _failed_delivery_record(
    contract: ServiceContract[Any], input_index: int, duration_ms: int
) -> SampleRecord:
    """The per-sample record of an undelivered response: no content, all skipped."""
    outcomes: list[tuple[str, Outcome]] = []
    for criterion in contract.criteria:
        outcomes.extend(_skipped_outcomes(criterion))
    return SampleRecord(
        input_index=input_index,
        postconditions=tuple(outcomes),
        execution_time_ms=duration_ms,
        content="",
        passed=False,
    )


def _judge(criterion: Criterion, tally: CriterionTally) -> tuple[float | None, Verdict | None]:
    """A thresholded criterion's bound and verdict; (None, None) otherwise.

    Two postures, per the criterion's decision artefact. A baseline-derived
    criterion carries an integer cutoff and passes iff the raw observed
    success count meets it — the confidence correction already lives in the
    derivation, so no second bound is stacked on the test side. A declared
    threshold is judged in the compliance posture: the test sample's own
    Wilson lower bound must clear it. The bound is reported in both
    postures; in the regression posture it is context, not the rule.
    """
    if criterion.threshold is None or tally.trials == 0:
        return None, None
    bound = wilson_lower_bound(tally.successes, tally.trials, criterion.confidence)
    if criterion.cutoff is not None:
        if criterion.cutoff > tally.trials:
            # A run too short for its cutoff cannot meet the bar; that is a
            # failed bar, not a defect.
            return bound, Verdict.FAIL
        return bound, evaluate_regression(tally.successes, tally.trials, criterion.cutoff).verdict
    verdict = Verdict.PASS if bound >= criterion.threshold else Verdict.FAIL
    return bound, verdict


class BarStanding(StrEnum):
    """A declared bar's experiment-time standing.

    ``UNSUPPORTABLE`` marks a bar that even a perfect run of this size could
    not have supported — the family's three-way experiment-time judgement,
    distinct from a bar that was simply not met.
    """

    MET = "met"
    NOT_MET = "not met"
    UNSUPPORTABLE = "unsupportable"


def bar_standing(result: "CriterionResult") -> BarStanding:
    """The recorded standing of a declared bar."""
    criterion = result.criterion
    if criterion.threshold is None:
        raise ValueError(f"criterion {criterion.name!r} declares no bar")
    if result.verdict is Verdict.PASS:
        return BarStanding.MET
    trials = result.tally.trials
    if criterion.cutoff is not None:
        # Regression posture: a perfect run supports the bar iff the run is
        # at least as long as the cutoff demands.
        return BarStanding.UNSUPPORTABLE if criterion.cutoff > trials else BarStanding.NOT_MET
    best_possible = wilson_lower_bound(trials, trials, criterion.confidence)
    if best_possible < criterion.threshold:
        return BarStanding.UNSUPPORTABLE
    return BarStanding.NOT_MET


def execute(
    contract: ServiceContract[Any],
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
        try:
            response = contract.invoke(plan.inputs[input_index])
        except ServiceDeliveryError as failure:
            # An anticipated failed delivery: a failed sample, counted
            # against every criterion with the cause as its reason — the
            # run completes to a verdict, and the reason surfaces where
            # every other failure reason does. Other exceptions remain
            # defects and abort.
            duration_ms = round((time.perf_counter() - invoked_at) * 1000)
            _record_failed_delivery(contract, tallies, str(failure))
            if record_samples:
                sample_records.append(_failed_delivery_record(contract, input_index, duration_ms))
            if on_sample is not None:
                on_sample(i + 1, plan.samples)
            continue
        duration_ms = round((time.perf_counter() - invoked_at) * 1000)
        views = TrialViews(response, contract.views)  # one cache per trial, all criteria
        trial_passed = True
        outcomes: list[tuple[str, Outcome]] = []
        failure_reasons: list[tuple[str, str]] = []
        for criterion in contract.criteria:
            try:
                evaluation = evaluate_trial(criterion, views)
            except TrialDefectError as defect:
                # A defect (not a TransformError) escaped this trial's
                # transform or postcondition. It is not a countable outcome
                # and not a sample: rather than let a bare traceback unwind
                # the run, enrich it with the driving input's structural
                # context and let it propagate for the orchestration layer to
                # contain at the configuration boundary.
                raise DefectDiagnosisError(
                    view=defect.view,
                    criterion=defect.criterion,
                    postcondition=defect.postcondition,
                    exception_type=type(defect.original).__name__,
                    exception_text=str(defect.original),
                    input_index=input_index,
                    input_excerpt=bounded_excerpt(str(plan.inputs[input_index])),
                ) from defect.original
            tallies[criterion.name].record(evaluation)
            trial_passed = trial_passed and evaluation.passed
            outcomes.extend(evaluation.outcomes)
            if not evaluation.passed and evaluation.reason:
                failure_reasons.append((criterion.name, evaluation.reason))
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
                    failure_reasons=tuple(failure_reasons),
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
