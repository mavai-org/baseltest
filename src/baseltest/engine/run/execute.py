"""The sampling loop: run a plan, judge each criterion, compose the verdict.

Structured as ``preflight → map → reduce → judge → compose``. The **map**
(:func:`_run_one_sample`) is a pure function of its inputs and the injected
service call — it samples once and judges every criterion without touching any
shared run state. The **reduce** (:func:`_reduce_samples`) folds the per-sample
outcomes into the run's tallies and ordered records, in ascending sample
ordinal, so the result is identical however the outcomes arrived: serial today,
and a future bounded-parallel executor could replace the sequential driver
without changing either the map or the funnel. The value model, feasibility,
identity, and judgement it composes live in sibling modules.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _SampleOutcome:
    """One sample's fully-computed result, before accumulation.

    The pure per-sample unit's output: everything the funnel needs to fold,
    and nothing shared. ``ordinal`` is the sample's position in the run — its
    sort key, distinct from the cycled input index — so the funnel can restore
    run order regardless of the order samples complete in.
    """

    ordinal: int
    evaluations: tuple[tuple[str, TrialEvaluation], ...]
    trial_passed: bool
    duration_ms: int
    record: SampleRecord | None


def _skipped_outcomes(criterion: Criterion) -> tuple[tuple[str, Outcome], ...]:
    return tuple((p.name, Outcome.SKIPPED) for p in criterion.postconditions)


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


def _failed_delivery_outcome(
    contract: ServiceContract[Any],
    ordinal: int,
    input_index: int,
    duration_ms: int,
    reason: str,
    record_samples: bool,
) -> _SampleOutcome:
    """An anticipated failed delivery as a sample outcome: every criterion
    counts it a failure with the delivery cause as its reason."""
    evaluations = tuple(
        (
            criterion.name,
            TrialEvaluation(passed=False, reason=reason, outcomes=_skipped_outcomes(criterion)),
        )
        for criterion in contract.criteria
    )
    record = _failed_delivery_record(contract, input_index, duration_ms) if record_samples else None
    return _SampleOutcome(
        ordinal=ordinal,
        evaluations=evaluations,
        trial_passed=False,
        duration_ms=duration_ms,
        record=record,
    )


def _run_one_sample(
    contract: ServiceContract[Any],
    ordinal: int,
    inputs: tuple[Any, ...],
    record_samples: bool,
) -> _SampleOutcome:
    """Sample once and judge every criterion — the pure per-sample unit.

    A pure function of ``(contract, ordinal, inputs)`` and the injected
    service call, with no side effect beyond that call: it accumulates
    nothing, reads no shared state, and returns everything the funnel needs.
    An anticipated failed delivery becomes a failed outcome; a genuine defect
    (a bug in the testing machinery) is diagnosed and re-raised to abort.
    """
    input_index = ordinal % len(inputs)
    context = EvaluationContext(index=input_index, input=inputs[input_index])
    invoked_at = time.perf_counter()
    try:
        response = contract.invoke(context.input)
    except ServiceDeliveryError as failure:
        # An anticipated failed delivery: a failed sample, counted against
        # every criterion with the cause as its reason — the run completes to
        # a verdict, and the reason surfaces where every other failure reason
        # does. Other exceptions remain defects and abort.
        duration_ms = round((time.perf_counter() - invoked_at) * 1000)
        return _failed_delivery_outcome(
            contract, ordinal, context.index, duration_ms, str(failure), record_samples
        )
    duration_ms = round((time.perf_counter() - invoked_at) * 1000)
    views = TrialViews(response, contract.views)  # one cache per trial, all criteria
    evaluations: list[tuple[str, TrialEvaluation]] = []
    outcomes: list[tuple[str, Outcome]] = []
    failure_reasons: list[tuple[str, str]] = []
    trial_passed = True
    for criterion in contract.criteria:
        try:
            evaluation = evaluate_trial(criterion, views, context)
        except TrialDefectError as defect:
            # A defect (not a TransformError) escaped this trial's transform or
            # postcondition. It is not a countable outcome and not a sample:
            # rather than let a bare traceback unwind the run, enrich it with
            # the driving input's structural context and let it propagate for
            # the orchestration layer to contain at the configuration boundary.
            raise DefectDiagnosisError(
                view=defect.view,
                criterion=defect.criterion,
                postcondition=defect.postcondition,
                exception_type=type(defect.original).__name__,
                exception_text=str(defect.original),
                input_index=context.index,
                input_excerpt=bounded_excerpt(str(context.input)),
            ) from defect.original
        evaluations.append((criterion.name, evaluation))
        trial_passed = trial_passed and evaluation.passed
        outcomes.extend(evaluation.outcomes)
        if not evaluation.passed and evaluation.reason:
            failure_reasons.append((criterion.name, evaluation.reason))
    record = (
        SampleRecord(
            input_index=context.index,
            postconditions=tuple(outcomes),
            execution_time_ms=duration_ms,
            content=response,
            passed=trial_passed,
            failure_reasons=tuple(failure_reasons),
        )
        if record_samples
        else None
    )
    return _SampleOutcome(
        ordinal=ordinal,
        evaluations=tuple(evaluations),
        trial_passed=trial_passed,
        duration_ms=duration_ms,
        record=record,
    )


def _run_samples(
    contract: ServiceContract[Any],
    plan: RunPlan,
    on_sample: Callable[[int, int], None] | None,
    record_samples: bool,
) -> list[_SampleOutcome]:
    """Map the pure per-sample unit over the plan's samples.

    Sequential today; because ``_run_one_sample`` is pure and the funnel is
    order-independent, a bounded-parallel executor could replace this loop
    without touching either. ``on_sample`` observes completions for progress
    display and can never alter the run.
    """
    outcomes: list[_SampleOutcome] = []
    for ordinal in range(plan.samples):
        outcomes.append(_run_one_sample(contract, ordinal, plan.inputs, record_samples))
        if on_sample is not None:
            on_sample(ordinal + 1, plan.samples)
    return outcomes


def _reduce_samples(
    contract: ServiceContract[Any], outcomes: list[_SampleOutcome]
) -> tuple[dict[str, CriterionTally], int, tuple[SampleRecord, ...], list[int]]:
    """Fold sample outcomes into the run's tallies and ordered records.

    Order-independent by construction: outcomes are folded in ascending
    ordinal, so tallies, per-sample records, and passing durations are
    identical whatever order the outcomes arrive in — serial today, and a
    future reordered or parallel execution produce byte-identical artefacts.
    """
    tallies = {criterion.name: CriterionTally() for criterion in contract.criteria}
    overall_successes = 0
    sample_records: list[SampleRecord] = []
    passing_durations_ms: list[int] = []
    for outcome in sorted(outcomes, key=lambda o: o.ordinal):
        for name, evaluation in outcome.evaluations:
            tallies[name].record(evaluation)
        overall_successes += int(outcome.trial_passed)
        if outcome.trial_passed:
            passing_durations_ms.append(outcome.duration_ms)
        if outcome.record is not None:
            sample_records.append(outcome.record)
    return tallies, overall_successes, tuple(sample_records), passing_durations_ms


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
    outcomes = _run_samples(contract, plan, on_sample, record_samples)
    finished_at = datetime.now(tz=UTC)
    tallies, overall_successes, sample_records, passing_durations_ms = _reduce_samples(
        contract, outcomes
    )

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
        samples=sample_records,
    )
