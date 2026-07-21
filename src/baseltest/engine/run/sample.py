"""The pure per-sample unit: sample once, judge every criterion.

This is the map half of the sampling loop. :func:`_run_one_sample` is a pure
function of ``(contract, ordinal, inputs)`` and the injected service call, with
no side effect beyond that call: it accumulates nothing, reads no shared run
state, and returns a self-contained :class:`_SampleOutcome`. Its purity is what
leaves bounded-parallel execution unprecluded — the funnel in ``execute`` folds
the outcomes back together, order-independently.
"""

import time
from dataclasses import dataclass
from typing import Any

from baseltest.contract import (
    Criterion,
    EvaluationContext,
    Outcome,
    ServiceContract,
    ServiceDeliveryError,
    TrialDefectError,
    TrialEvaluation,
    TrialViews,
    evaluate_trial,
)

from ..defect import DefectDiagnosisError
from ..naming import bounded_excerpt
from .model import SampleRecord


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
