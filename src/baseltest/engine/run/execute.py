"""The sampling loop: run a plan, judge each criterion, compose the verdict.

This is what the ``run`` package is about — cycling a plan's inputs through
the service, evaluating each response against every criterion, and folding the
per-sample outcomes into a :class:`RunResult`. The value model, feasibility,
identity, and judgement it composes live in sibling modules.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from baseltest.contract import (
    Criterion,
    CriterionTally,
    EvaluationContext,
    Outcome,
    ServiceContract,
    ServiceDeliveryError,
    TrialDefectError,
    TrialEvaluation,
    TrialViews,
    evaluate_trial,
)
from baseltest.statistics.verdict import Verdict

from ..defect import DefectDiagnosisError
from ..latency import evaluate_latency
from ..naming import bounded_excerpt
from .feasibility import _preflight
from .identity import inputs_fingerprint
from .judge import _judge
from .model import CriterionResult, RunPlan, RunResult, SampleRecord


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
        context = EvaluationContext(index=input_index, input=plan.inputs[input_index])
        invoked_at = time.perf_counter()
        try:
            response = contract.invoke(context.input)
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
                evaluation = evaluate_trial(criterion, views, context)
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
                    input_index=context.index,
                    input_excerpt=bounded_excerpt(str(context.input)),
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
