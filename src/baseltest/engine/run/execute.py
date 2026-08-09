"""The sampling loop: run a plan, judge each criterion, compose the verdict.

Structured as ``preflight → map → reduce → judge → compose``. The **map** is
the pure per-sample unit in :mod:`.sample`; here we drive it over the plan
(:func:`_run_samples`), **reduce** the outcomes into the run's tallies and
ordered records (:func:`_reduce_samples`, folding in ascending sample ordinal
so the result is order-independent), then judge and compose. Because the
per-sample unit is pure and the funnel order-independent, a future
bounded-parallel executor could replace the sequential driver without changing
either. The value model, feasibility, identity, and judgement it composes live
in sibling modules.
"""

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from baseltest.contract import (
    CriterionTally,
    FailureKind,
    ObservedValue,
    Outcome,
    Postcondition,
    PostconditionStanding,
    ServiceContract,
)
from baseltest.statistics.verdict import Verdict

from ..latency import evaluate_latency
from ..naming import bounded_key
from .feasibility import _preflight
from .identity import inputs_fingerprint
from .judge import _judge
from .model import (
    CriterionResult,
    FailureAttribution,
    RunPlan,
    RunResult,
    SampleRecord,
)
from .sample import _run_one_sample, _SampleOutcome


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


# A failed trial the run can attribute to nothing it stated: no failing
# check, and no delivery cause because the raiser gave none. The kind is
# still knowable — nothing was judged — so it is stated as a delivery with
# an identity that says exactly that and claims nothing further.
_UNATTRIBUTED_FAILURE = "undelivered"


def _attribute_failures(outcomes: list[_SampleOutcome]) -> tuple[FailureAttribution, ...]:
    """Attribute each failed trial once, to the first thing that failed it.

    Pure and order-independent, folded over the same outcomes the tallies
    are: a trial that never delivered is attributed to its stated cause,
    and any other failed trial to the first check that did not hold, in
    the contract's own order. Trials, not check-evaluations — the unit the
    reader authored and the one every other count on the page is in.

    Deliberately not derived from the per-criterion tallies. A trial that
    fails two criteria appears in both, and an undelivered trial fails
    every one of them, so summing those tallies would multiply a single
    incident by the width of the contract.
    """
    counts: Counter[tuple[str, FailureKind]] = Counter()
    for outcome in sorted(outcomes, key=lambda o: o.ordinal):
        if outcome.trial_passed:
            continue
        cause = next(
            (
                evaluation.delivery_cause
                for _, evaluation in outcome.evaluations
                if evaluation.delivery_cause is not None
            ),
            None,
        )
        if cause is not None:
            counts[(str(cause), FailureKind.DELIVERY)] += 1
            continue
        check = next(
            (
                name
                for _, evaluation in outcome.evaluations
                for name, status in evaluation.outcomes
                if status is Outcome.FAILED
            ),
            None,
        )
        # A failed trial with no failing check and no stated cause: an
        # author's own delivery failure, or a transform that yielded
        # nothing. The kind is knowable, the identity is not, and neither
        # is invented.
        if check is None:
            counts[(_UNATTRIBUTED_FAILURE, FailureKind.DELIVERY)] += 1
        else:
            counts[(bounded_key(check), FailureKind.EVALUATED)] += 1
    return tuple(
        FailureAttribution(condition=condition, count=count, kind=kind)
        for (condition, kind), count in sorted(counts.items())
    )


def _reduce_samples(
    contract: ServiceContract[Any], outcomes: list[_SampleOutcome]
) -> tuple[
    dict[str, CriterionTally],
    dict[str, tuple[PostconditionStanding, ...]],
    int,
    tuple[SampleRecord, ...],
    list[int],
    int,
]:
    """Fold sample outcomes into the run's tallies, standings, and records.

    Order-independent by construction: outcomes are folded in ascending
    ordinal, so tallies, standings, per-sample records, and passing
    durations are identical whatever order the outcomes arrive in — serial
    today, and a future reordered or parallel execution produce
    byte-identical artefacts.

    The standings are the per-postcondition aggregation of the evaluations'
    ``outcomes`` — data every trial already computes — keyed per criterion
    by ``(input index, check name)``, rows ordered by input then first
    evaluation. Descriptive only: counts, never inference.
    """
    tallies = {criterion.name: CriterionTally() for criterion in contract.criteria}
    counts: dict[str, dict[tuple[int, str], list[int]]] = {
        criterion.name: {} for criterion in contract.criteria
    }
    descriptors = {
        criterion.name: {pc.name: pc for pc in criterion.postconditions}
        for criterion in contract.criteria
    }
    values: dict[str, dict[tuple[int, str], dict[tuple[str, bool], int]]] = {
        criterion.name: {} for criterion in contract.criteria
    }
    overall_successes = 0
    total_tokens = 0
    sample_records: list[SampleRecord] = []
    passing_durations_ms: list[int] = []
    tick = {Outcome.PASSED: 0, Outcome.FAILED: 1, Outcome.SKIPPED: 2}
    for outcome in sorted(outcomes, key=lambda o: o.ordinal):
        for name, evaluation in outcome.evaluations:
            tallies[name].record(evaluation)
            per_check = counts[name]
            excerpts = dict(evaluation.subjects)
            for check, status in evaluation.outcomes:
                row = per_check.setdefault((outcome.input_index, check), [0, 0, 0])
                row[tick[status]] += 1
                excerpt = excerpts.get(check)
                if excerpt is not None and status is not Outcome.SKIPPED:
                    value_tally = values[name].setdefault((outcome.input_index, check), {})
                    key = (excerpt, status is Outcome.PASSED)
                    value_tally[key] = value_tally.get(key, 0) + 1
        overall_successes += int(outcome.trial_passed)
        total_tokens += outcome.tokens or 0
        if outcome.trial_passed:
            passing_durations_ms.append(outcome.duration_ms)
        if outcome.record is not None:
            sample_records.append(outcome.record)
    standings = {
        name: tuple(
            _standing(
                input_index,
                check,
                row,
                descriptors[name].get(check),
                values[name].get((input_index, check), {}),
            )
            for (input_index, check), row in sorted(per_check.items(), key=lambda item: item[0][0])
        )
        for name, per_check in counts.items()
    }
    return (
        tallies,
        standings,
        overall_successes,
        tuple(sample_records),
        passing_durations_ms,
        total_tokens,
    )


# Distinct obtained-value exemplars stated per standings row; the remainder
# is elided with its count — bounded documents, deterministic fold.
_EXEMPLAR_CAP = 4


def _standing(
    input_index: int,
    check: str,
    row: list[int],
    descriptor: Postcondition | None,
    value_tally: dict[tuple[str, bool], int],
) -> PostconditionStanding:
    """One standings row: counts, the check's stated structure, and capped
    obtained-value exemplars — failing exemplars first, then descending
    count, then lexical, so a reordered or parallel fold emits
    byte-identical artefacts."""
    ordered = sorted(value_tally.items(), key=lambda item: (item[0][1], -item[1], item[0][0]))
    exemplars = tuple(
        ObservedValue(excerpt=excerpt, count=count, held=held)
        for (excerpt, held), count in ordered[:_EXEMPLAR_CAP]
    )
    elided = sum(count for _, count in ordered[_EXEMPLAR_CAP:])
    return PostconditionStanding(
        input_index=input_index,
        postcondition=check,
        passed=row[0],
        failed=row[1],
        skipped=row[2],
        optional=descriptor is not None and not descriptor.required,
        path=descriptor.path if descriptor is not None else None,
        form=descriptor.form if descriptor is not None else None,
        expected=descriptor.expected if descriptor is not None else None,
        observed=exemplars,
        elided=elided,
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
    outcomes = _run_samples(contract, plan, on_sample, record_samples)
    finished_at = datetime.now(tz=UTC)
    (
        tallies,
        standings,
        overall_successes,
        sample_records,
        passing_durations_ms,
        total_tokens,
    ) = _reduce_samples(contract, outcomes)

    results = []
    for criterion in contract.criteria:
        tally = tallies[criterion.name]
        bound, verdict = _judge(criterion, tally)
        results.append(
            CriterionResult(
                criterion=criterion,
                tally=tally,
                lower_bound=bound,
                verdict=verdict,
                standings=standings[criterion.name],
            )
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
        total_tokens=total_tokens,
        failure_attribution=_attribute_failures(outcomes),
    )
