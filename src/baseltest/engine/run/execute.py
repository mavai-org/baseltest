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

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from baseltest.contract import CriterionTally, ServiceContract
from baseltest.statistics.verdict import Verdict

from ..latency import evaluate_latency
from .feasibility import _preflight
from .identity import inputs_fingerprint
from .judge import _judge
from .model import CriterionResult, RunPlan, RunResult, SampleRecord
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
