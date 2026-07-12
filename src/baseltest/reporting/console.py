"""Console rendering of run results, in the contract format's own vocabulary."""

from collections import Counter
from collections.abc import Sequence

from baseltest.engine import (
    CriterionResult,
    InfeasibleRunError,
    LatencyEvaluation,
    RunKind,
    RunResult,
    Verdict,
    bar_standing,
)


def _percent(confidence: float) -> str:
    percent = confidence * 100
    return f"{percent:.0f}%" if percent == int(percent) else f"{percent}%"


def _variance(successes: int, trials: int) -> float:
    """Sample variance of the observed Bernoulli rate."""
    if trials == 0:
        return 0.0
    rate = successes / trials
    return rate * (1 - rate)


def _verdict_lines(result: CriterionResult) -> list[str]:
    criterion = result.criterion
    tally = result.tally
    assert (
        result.verdict is not None
        and result.lower_bound is not None
        and criterion.threshold is not None
    )
    source = ""
    if criterion.provenance.contract_ref is not None:
        source = f" ({criterion.provenance.origin}, {criterion.provenance.contract_ref})"
    if criterion.cutoff is not None:
        # Regression posture: the integer cutoff is the stated decision
        # artefact; the derived threshold is its construction, reported as
        # context.
        relation = "meets" if result.verdict is Verdict.PASS else "misses"
        explanation = (
            f"    {tally.successes} passing {relation} the required {criterion.cutoff} of "
            f"{tally.trials} — the cutoff already carries the "
            f"{_percent(criterion.confidence)} confidence of its derivation "
            f"(threshold {criterion.threshold:.4f}){source}"
        )
    else:
        relation = "clears" if result.verdict is Verdict.PASS else "below"
        explanation = (
            f"    observed rate {tally.observed_rate:.4f}; we can be "
            f"{_percent(criterion.confidence)} confident the true rate is at least "
            f"{result.lower_bound:.4f} — {relation} your {criterion.threshold} "
            f"threshold{source}"
        )
    return [
        f"  criterion {criterion.name}: {result.verdict.value.upper()}",
        f"    {tally.successes} of {tally.trials} responses met expectations",
        explanation,
        *(_failure_reason_lines(result) if result.verdict is Verdict.FAIL else []),
    ]


def _failure_reason_lines(result: CriterionResult, limit: int = 3) -> list[str]:
    """The most common failure reasons — a FAIL should say what failed."""
    reasons = result.tally.failure_reasons
    if not reasons:
        return []
    lines = [f"      {count}× {reason}" for reason, count in reasons.most_common(limit)]
    remainder = len(reasons) - limit
    if remainder > 0:
        lines.append(f"      … and {remainder} further reason(s)")
    return lines


def _characterised_lines(
    result: CriterionResult, label: str = "no threshold declared"
) -> list[str]:
    tally = result.tally
    return [
        f"  criterion {result.name}: recorded ({label})",
        (
            f"    {tally.successes} of {tally.trials} responses met expectations "
            f"(observed rate {tally.observed_rate:.4f}, "
            f"variance {_variance(tally.successes, tally.trials):.4f})"
        ),
        *_failure_reason_lines(result),
    ]


def _recorded_bar_lines(result: CriterionResult) -> list[str]:
    """A declared bar under measure: noted against the evidence — data, not a verdict."""
    criterion = result.criterion
    assert result.lower_bound is not None and criterion.threshold is not None
    standing = bar_standing(result)
    if standing == "unsupportable":
        note = (
            f"    declared bar {criterion.threshold}: judgement unsupportable at "
            f"{result.tally.trials} samples — even a perfect run of this size could "
            "not support the bar — recorded, not a verdict"
        )
    else:
        note = (
            f"    declared bar {criterion.threshold}: the evidence records it as "
            f"{standing} ({_percent(criterion.confidence)} lower bound "
            f"{result.lower_bound:.4f}) — recorded, not a verdict"
        )
    lines = _characterised_lines(result, label="bar declared")
    lines.insert(2, note)
    return lines


def _latency_lines(evaluation: LatencyEvaluation) -> list[str]:
    """The latency dimension: observed percentiles and per-bound outcomes."""
    bar = evaluation.bar
    source = "declared ceiling"
    if bar.origin == "baseline-derived":
        source = (
            f"no worse than measured ({_percent(bar.confidence)} bound from "
            f"{bar.provenance.contract_ref})"
        )
    elif bar.provenance.contract_ref is not None:
        source = f"declared ceiling ({bar.provenance.origin}, {bar.provenance.contract_ref})"
    lines = [
        f"  latency: {evaluation.verdict.value.upper()} — {source}",
        (
            f"    {evaluation.contributing_samples} of {evaluation.total_samples} "
            "samples passed and contribute durations"
        ),
    ]
    for outcome in evaluation.evaluations:
        bound = outcome.bound
        if outcome.status == "infeasible":
            lines.append(f"    {bound.percentile}: no judgement — {outcome.reason}")
            continue
        relation = "within" if outcome.status == "pass" else "breaches"
        detail = ""
        if bound.rank is not None and bound.baseline_samples is not None:
            detail = (
                f" (bound is the baseline's {_ordinal(bound.rank)} of "
                f"{bound.baseline_samples} sorted latencies; "
                f"baseline {bound.percentile} was {bound.baseline_percentile_ms}ms)"
            )
        lines.append(
            f"    {bound.percentile}: observed {outcome.observed_ms}ms {relation} "
            f"the {bound.threshold_ms}ms bound{detail}"
        )
    return lines


def _ordinal(rank: int) -> str:
    suffix = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


# javai-ref: JVI-51ASAR0 — do not remove (resolves in javai-orchestrator)
def render_run(result: RunResult, baseline_path: str | None = None) -> str:
    """Render a run result in the honest-output shapes.

    Under test: per-criterion verdict lines plus the composite. Under
    measure: pure recording — every criterion's evidence, a declared bar
    noted as met / not met (data, never a verdict). When a baseline
    artefact was persisted, its path is named.
    """
    lines: list[str] = []
    if result.kind is RunKind.MEASURE:
        lines.append(
            f"contract {result.contract_id}: recorded "
            "(a measure run records; it renders no verdict)"
        )
        for criterion_result in result.criterion_results:
            if criterion_result.criterion.threshold is not None:
                lines.extend(_recorded_bar_lines(criterion_result))
            else:
                lines.extend(_characterised_lines(criterion_result))
    elif result.composite is not None:
        lines.append(f"contract {result.contract_id}: {result.composite.value.upper()}")
        for criterion_result in result.criterion_results:
            if criterion_result.verdict is not None:
                lines.extend(_verdict_lines(criterion_result))
            else:
                lines.extend(_characterised_lines(criterion_result))
        if result.latency is not None:
            lines.extend(_latency_lines(result.latency))
    else:
        lines.append(
            f"contract {result.contract_id}: OBSERVATION "
            "(no threshold declared — this is a measurement, not a verdict)"
        )
        for criterion_result in result.criterion_results:
            lines.extend(_characterised_lines(criterion_result))
    if baseline_path is not None:
        lines.append(f"  baseline written: {baseline_path}")
    return "\n".join(lines)


def render_run_plan(
    samples: int,
    provenance: str,
    demanded_by: str | None = None,
    threshold: float | None = None,
    per_configuration: bool = False,
) -> str:
    """The run-plan line: every run states its N and where the value came from.

    Printed before the first invocation, informative in tone, one of three
    provenance forms — ``derived`` (the thresholds set the minimum),
    ``explicit`` (a flag sized the run), or ``default`` (the verb's fixed
    default, with the flag named for when the developer wants to size it).
    """
    unit = " per configuration" if per_configuration else ""
    flag = "--samples-per-config" if per_configuration else "--samples"
    if provenance == "risk-driven":
        return f"n = {samples}{unit} (risk-driven: computed from your declared tolerance)"
    if provenance == "derived":
        detail = f"derived: threshold {threshold} requires at least {samples} samples"
        if demanded_by is not None:
            detail = (
                f"derived: criterion {demanded_by}'s threshold {threshold} "
                f"requires at least {samples} samples"
            )
        return f"n = {samples}{unit} ({detail})"
    if provenance == "explicit":
        return f"n = {samples}{unit} (set via {flag})"
    return f"n = {samples}{unit} (default; use {flag} to size the run)"


def render_explorations(
    contract_id: str,
    samples_per_config: int,
    entries: Sequence[tuple[str, RunResult, str]],
) -> str:
    """Render an explore run's summary: descriptive, one line pair per configuration.

    Each entry is ``(label, result, artefact_path)`` — the label is the
    configuration's factor-derived stem, the same one its artefact file
    carries. No verdict vocabulary appears anywhere: an exploration
    records what each configuration did; judging one is a test's job.
    """
    count = len(entries)
    plural = "" if count == 1 else "s"
    lines = [
        f"contract {contract_id}: explored {count} configuration{plural}, "
        f"{samples_per_config} sample(s) each (descriptive — an exploration "
        "renders no verdict)"
    ]
    for label, result, path in entries:
        successes = result.overall_successes
        total = result.plan.samples
        rate = successes / total if total else 0.0
        lines.append(
            f"  configuration {label}: {successes} of {total} responses met "
            f"expectations (observed rate {rate:.4f})"
        )
        reasons: Counter[str] = Counter()
        for criterion_result in result.criterion_results:
            reasons.update(criterion_result.tally.failure_reasons)
        if reasons:
            reason, count = reasons.most_common(1)[0]
            lines.append(f"    most common failure: {count}× {reason}")
        lines.append(f"    artefact: {path}")
    lines.append("  compare configurations by diffing their artefacts")
    return "\n".join(lines)


def render_infeasible(contract_name: str, error: InfeasibleRunError) -> str:
    """Render the constructive refusal for an infeasible verification run."""
    lines = [f"contract {contract_name}: cannot run as declared"]
    for criterion in error.infeasible:
        lines.append(
            f"  {error.samples} samples cannot support criterion "
            f"{criterion.name}'s threshold of {criterion.threshold} at "
            f"{_percent(criterion.confidence)} confidence."
        )
    lines.append(
        f"  Either raise samples to at least {error.governing_minimum}, or declare "
        "`intent: smoke` to run an informal check that renders no statistical verdict."
    )
    return "\n".join(lines)
