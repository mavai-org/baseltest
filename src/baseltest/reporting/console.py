"""Console rendering of run results, in the task format's own vocabulary."""

from baseltest.engine import CriterionResult, InfeasibleRunError, RunResult, Verdict


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
    relation = "clears" if result.verdict is Verdict.PASS else "below"
    source = ""
    if criterion.provenance.contract_ref is not None:
        source = f" ({criterion.provenance.origin}, {criterion.provenance.contract_ref})"
    return [
        f"  criterion {criterion.name}: {result.verdict.value.upper()}",
        f"    {tally.successes} of {tally.trials} responses met expectations",
        (
            f"    observed rate {tally.observed_rate:.4f}; we can be "
            f"{_percent(criterion.confidence)} confident the true rate is at least "
            f"{result.lower_bound:.4f} — {relation} your {criterion.threshold} "
            f"threshold{source}"
        ),
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


def _characterised_lines(result: CriterionResult) -> list[str]:
    tally = result.tally
    return [
        f"  criterion {result.name}: measured (no threshold declared)",
        (
            f"    {tally.successes} of {tally.trials} responses met expectations "
            f"(observed rate {tally.observed_rate:.4f}, "
            f"variance {_variance(tally.successes, tally.trials):.4f})"
        ),
        *_failure_reason_lines(result),
    ]


# javai-ref: JVI-51ASAR0 — do not remove (resolves in javai-orchestrator)
def render_run(result: RunResult, baseline_path: str | None = None) -> str:
    """Render a run result in the honest-output shapes.

    With at least one thresholded criterion: per-criterion verdict lines
    plus the composite. Without any: an observation, labelled as a
    measurement, no verdict vocabulary. When a baseline artefact was
    persisted, its path is named.
    """
    lines: list[str] = []
    if result.composite is not None:
        lines.append(f"task {result.contract_id}: {result.composite.value.upper()}")
        for criterion_result in result.criterion_results:
            if criterion_result.verdict is not None:
                lines.extend(_verdict_lines(criterion_result))
            else:
                lines.extend(_characterised_lines(criterion_result))
    else:
        lines.append(
            f"task {result.contract_id}: OBSERVATION "
            "(no threshold declared — this is a measurement, not a verdict)"
        )
        for criterion_result in result.criterion_results:
            lines.extend(_characterised_lines(criterion_result))
    if baseline_path is not None:
        lines.append(f"  baseline written: {baseline_path}")
    return "\n".join(lines)


def render_infeasible(task_name: str, error: InfeasibleRunError) -> str:
    """Render the constructive refusal for an infeasible verification run."""
    lines = [f"task {task_name}: cannot run as declared"]
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
