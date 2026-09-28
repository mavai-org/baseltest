"""Console rendering of run results, in the contract format's own vocabulary."""

from collections import Counter
from collections.abc import Mapping, Sequence

from baseltest.engine import (
    METHODOLOGY_VERSION,
    BoundEvaluation,
    ComplianceVerdict,
    ConfigurationError,
    ConfigurationRefusedError,
    CriterionResult,
    LatencyEvaluation,
    LatencyPlanning,
    RegressionVerdict,
    RunKind,
    RunResult,
    Verdict,
    bar_attainment,
)


def _verdict_row(result: CriterionResult) -> tuple[str, str, str, str, str, str, str]:
    """One judged criterion's table cells: name, verdict, passed, required,
    threshold, rule, basis."""
    criterion = result.criterion
    tally = result.tally
    decision = result.decision
    assert decision is not None
    if isinstance(decision, RegressionVerdict):
        # The integer cutoff is the decision artefact; c / n_t displays it.
        required = str(decision.cutoff)
        threshold = f"{decision.derivation.threshold_real:.4f}"
    else:
        required = "—" if decision.minimum_passing is None else str(decision.minimum_passing)
        threshold = f"{decision.requirement:g}"
    basis = criterion.provenance.origin
    if criterion.provenance.contract_ref is not None:
        basis = f"{basis} — {criterion.provenance.contract_ref}"
    return (
        criterion.name,
        decision.verdict.value.upper(),
        f"{tally.successes}/{tally.trials}",
        required,
        threshold,
        decision.rule.value,
        basis,
    )


def _verdict_table(results: Sequence[CriterionResult]) -> list[str]:
    """The judged criteria as one aligned table, a row per criterion; the
    decision's disclosures and the most common failure reasons stay
    indented beneath each row."""
    headers = ("criterion", "verdict", "passed", "required", "threshold", "rule", "basis")
    rows = [_verdict_row(result) for result in results]
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    lines = ["  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    left_aligned = {0, 1, len(headers) - 2, len(headers) - 1}
    for result, row in zip(results, rows, strict=True):
        cells = [
            cell.ljust(width) if i in left_aligned else cell.rjust(width)
            for i, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        lines.append(("  " + "  ".join(cells)).rstrip())
        lines.extend(_decision_lines(result))
        if result.verdict is Verdict.FAIL:
            lines.extend(_failure_reason_lines(result))
    return lines


def _decision_lines(result: CriterionResult) -> list[str]:
    """What a decision discloses beside its verdict: for compliance, whether
    a pass was possible and the Clopper–Pearson bound; for regression, the
    size at the assumed common rate and what the design can detect."""
    decision = result.decision
    if isinstance(decision, ComplianceVerdict):
        if not decision.pass_possible:
            return [
                f"      PASS not possible at this size (n = {decision.trials}): this result "
                "carries no evidence about the service"
            ]
        return [
            f"      one-sided Clopper–Pearson lower bound {decision.clopper_pearson_lower:.4f}"
            f" at alpha {decision.alpha:g}"
        ]
    assert isinstance(decision, RegressionVerdict)
    lines = []
    size = decision.derivation.size_at_assumed_common_rate
    if size is not None:
        lines.append(
            f"      size at the assumed common rate {size:.4f} (were the true rate the "
            "baseline's observed rate; not a property of this run)"
        )
    power = result.power
    if power is not None:
        if power.design_alternative_rate is not None:
            assert power.design_power is not None and power.resolved_power is not None
            lines.append(
                f"      at the design alternative rate {power.design_alternative_rate:g}: "
                f"design power {power.design_power:.3f}, resolved power "
                f"{power.resolved_power:.3f}"
            )
        mdd = power.minimum_detectable_degradation
        if mdd is None:
            lines.append("      minimum detectable degradation: none at 80% design power")
        else:
            lines.append(
                f"      minimum detectable degradation {mdd:.4f} at 80% power "
                "(inverts the design power)"
            )
    return lines


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


def _standings_lines(result: CriterionResult, named: bool = False) -> list[str]:
    """The criterion's per-check standings: descriptive triage.

    Counts and an observed fraction per ``(input, check)`` — which checks
    fail, on which inputs, how often. Deliberately no interval, no
    threshold, and no verdict vocabulary: the run is sized for the
    criterion's claim, not for bounding each check.
    """
    if not result.standings:
        return []
    subject = f" for criterion {result.name}" if named else ""
    lines = [f"    standings{subject} (descriptive — counts, not verdicts):"]
    for row in result.standings:
        detail = f"{row.passed}/{row.trials} passed ({row.observed_fraction:.2f})"
        extras = [
            f"{count} {label}"
            for count, label in ((row.failed, "failed"), (row.skipped, "skipped"))
            if count
        ]
        if extras:
            detail += " — " + ", ".join(extras)
        lines.append(f"      input {row.input_index} · {row.postcondition}: {detail}")
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
            f"variance {tally.variance:.4f})"
        ),
        *_failure_reason_lines(result),
    ]


def _recorded_bar_lines(result: CriterionResult) -> list[str]:
    """A declared bar under measure: noted against the evidence — data, not a verdict."""
    decision = result.decision
    assert isinstance(decision, ComplianceVerdict)
    standing = bar_attainment(result)
    if standing == "unsupportable":
        note = (
            f"    declared bar {decision.requirement}: judgement unsupportable at "
            f"{result.tally.trials} samples — no outcome of this size can demonstrate "
            "it — recorded, not a verdict"
        )
    else:
        note = (
            f"    declared bar {decision.requirement}: the evidence records it as "
            f"{standing} (at least {decision.minimum_passing} of {decision.trials} needed, "
            f"{decision.rule.value}) — recorded, not a verdict"
        )
    lines = _characterised_lines(result, label="bar declared")
    lines.insert(2, note)
    return lines


def _latency_lines(evaluation: LatencyEvaluation) -> list[str]:
    """The latency dimension: its verdict, and one line per enforced constraint."""
    bar = evaluation.bar
    source = "declared ceilings"
    if bar.origin == "baseline-derived":
        source = f"no worse than measured (baseline {bar.provenance.contract_ref})"
    elif bar.provenance.contract_ref is not None:
        source = f"declared ceilings ({bar.provenance.origin}, {bar.provenance.contract_ref})"
    lines = [
        f"  latency: {evaluation.verdict.value.upper()} — {source}, alpha {bar.alpha:g}",
        (
            f"    {evaluation.contributing_samples} of {evaluation.total_samples} "
            "samples passed and contribute durations"
        ),
    ]
    lines.extend(_constraint_line(outcome) for outcome in evaluation.evaluations)
    return lines


def _constraint_line(outcome: BoundEvaluation) -> str:
    """One enforced constraint: its verdict and its decision artefact."""
    judgement = outcome.judgement
    label = outcome.bound.percentile
    verdict = outcome.verdict.value.upper()
    n_s = judgement.successful_latencies
    rule = judgement.rule.value if judgement.rule is not None else "advisory"
    if judgement.compliance is not None:
        decided = judgement.compliance
        head = f"    {label} ≤ {outcome.bound.threshold_ms}ms: {verdict} ({rule})"
        if decided.minimum_within is None:
            return (
                f"{head} — {n_s} successful latencies; no count of {n_s} can demonstrate "
                "the requirement"
            )
        raw = ""
        if decided.observed_percentile_ms is not None:
            raw = (
                f"; raw {label} {round(decided.observed_percentile_ms)}ms "
                "(a raw percentile comparison, advisory)"
            )
        return (
            f"{head} — {decided.within_threshold} of {n_s} successful latencies within, "
            f"at least {decided.minimum_within} needed{raw}"
        )
    head = f"    {label}: {verdict} ({rule})"
    indicative = " — indicative only" if judgement.indicative else ""
    nondegeneracy = judgement.nondegeneracy
    if nondegeneracy is not None and nondegeneracy.outcome == "INCONCLUSIVE":
        return (
            f"{head} — {n_s} successful latencies, below the {label} minimum; "
            "the percentile is degenerate"
        )
    precedence = judgement.precedence
    if precedence is None or precedence.saturated or judgement.observed_ms is None:
        return (
            f"{head} — no baseline rank achieves alpha for {n_s} successful latencies (saturated)"
        )
    assert precedence.rank is not None and precedence.threshold is not None
    relation = "within" if outcome.verdict is Verdict.PASS else "breaches"
    return (
        f"{head} — observed {round(judgement.observed_ms)}ms {relation} the "
        f"{round(precedence.threshold)}ms threshold (the baseline's "
        f"{_ordinal(precedence.rank)} of {precedence.n} latencies, derived for "
        f"{n_s} successful latencies; baseline {label} was "
        f"{round(precedence.baseline_percentile)}ms){indicative}"
    )


def render_latency_planning(plans: Sequence[LatencyPlanning]) -> list[str]:
    """The pre-run latency warnings: planning figures on the expected count,
    never a refusal — both decisions are made after the run."""
    lines = []
    for plan in plans:
        label = plan.bound.percentile
        expected = plan.nondegeneracy.expected_test_samples
        if plan.nondegeneracy.warning:
            lines.append(
                f"warning: latency {label} expects {expected} successful latencies, below "
                f"its minimum of {plan.nondegeneracy.minimum_contributing_samples}; "
                f"{plan.nondegeneracy.planned_samples_needed} planned samples would expect "
                "enough (decided after the run on the actual count)"
            )
        if plan.precedence.warning:
            figure = plan.precedence.minimum_baseline_trials
            needed = (
                f"; a baseline of at least {figure} latencies supports one"
                if figure is not None
                else ""
            )
            lines.append(
                f"warning: latency {label}: no baseline rank achieves alpha for the "
                f"{expected} successful latencies expected{needed} (decided after the "
                "run on the actual count)"
            )
    return lines


def _ordinal(rank: int) -> str:
    suffix = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def _verdict_header(result: RunResult) -> list[str]:
    """The test verdict at the top: V_test, what triggered it, the two
    dimensions, and the Type-I envelopes by direction."""
    overall = result.overall
    assert overall is not None
    lines = [
        f"contract {result.contract_id} — verdict: {overall.verdict.value.upper()} "
        f"(methodology {METHODOLOGY_VERSION})"
    ]
    if overall.triggering:
        named = ", ".join(
            f"criterion {t.id}" if t.kind == "criterion" else t.id for t in overall.triggering
        )
        lines.append(f"  decided by: {named}")
    if overall.rate_verdict is not None and overall.latency_verdict is not None:
        lines.append(
            f"  functional: {overall.rate_verdict.value.upper()} · "
            f"latency: {overall.latency_verdict.value.upper()}"
        )
    envelopes = result.envelopes
    parts = []
    if envelopes.false_degradation_signal is not None:
        parts.append(f"false degradation signal ≤ {envelopes.false_degradation_signal:g}")
    if envelopes.false_compliance is not None:
        parts.append(f"false compliance ≤ {envelopes.false_compliance:g}")
    if parts:
        lines.append("  Type-I envelopes: " + "; ".join(parts))
    return lines


# mavai-ref: JVI-51ASAR0 — do not remove (resolves in mavai-orchestrator)
def render_run(result: RunResult, baseline_path: str | None = None) -> str:
    """Render a run result in the honest-output shapes.

    Under test: the composite verdict as the title line, then the judged
    criteria as one aligned table (failure reasons beneath a FAIL row) and
    any unthresholded criteria characterised beneath it. Under
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
            if criterion_result.decision is not None:
                lines.extend(_recorded_bar_lines(criterion_result))
            else:
                lines.extend(_characterised_lines(criterion_result))
            lines.extend(_standings_lines(criterion_result))
    elif result.overall is not None:
        lines.extend(_verdict_header(result))
        judged = [r for r in result.criterion_results if r.verdict is not None]
        if judged:
            lines.append("")
            lines.extend(_verdict_table(judged))
        for criterion_result in result.criterion_results:
            if criterion_result.verdict is None:
                lines.extend(_characterised_lines(criterion_result))
        for criterion_result in result.criterion_results:
            lines.extend(
                _standings_lines(criterion_result, named=len(result.criterion_results) > 1)
            )
        if result.latency is not None:
            lines.extend(_latency_lines(result.latency))
    else:
        lines.append(
            f"contract {result.contract_id}: OBSERVATION "
            "(no threshold declared — this is a measurement, not a verdict)"
        )
        for criterion_result in result.criterion_results:
            lines.extend(_characterised_lines(criterion_result))
            lines.extend(_standings_lines(criterion_result))
    if baseline_path is not None:
        lines.append(f"  baseline written: {baseline_path}")
    return "\n".join(lines)


def render_run_plan(
    samples: int,
    provenance: str,
    demanded_by: str | None = None,
    threshold: float | None = None,
    per_configuration: bool = False,
    per_iteration: bool = False,
) -> str:
    """The run-plan line: every run states its N and where the value came from.

    Printed before the first invocation, informative in tone, one of three
    provenance forms — ``derived`` (the thresholds set the minimum),
    ``explicit`` (a flag sized the run), or ``default`` (the verb's fixed
    default, with the flag named for when the developer wants to size it).
    A risk-driven run does not use this line: its sizing block's title
    already states n and where it came from.
    """
    unit = ""
    flag = "--samples"
    if per_configuration:
        unit, flag = " per configuration", "--samples-per-config"
    elif per_iteration:
        unit, flag = " per iteration", "--samples-per-iteration"
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
        lines.append(
            f"  configuration {label}: {result.overall_successes} of "
            f"{result.plan.samples} responses met expectations "
            f"(observed rate {result.observed_rate:.4f})"
        )
        reasons: Counter[str] = Counter()
        for criterion_result in result.criterion_results:
            reasons.update(criterion_result.tally.failure_reasons)
        if reasons:
            reason, count = reasons.most_common(1)[0]
            lines.append(f"    most common failure: {count}× {reason}")
        for criterion_result in result.criterion_results:
            lines.extend(
                "  " + line
                for line in _standings_lines(
                    criterion_result, named=len(result.criterion_results) > 1
                )
            )
        lines.append(f"    artefact: {path}")
    lines.append("  compare configurations by diffing their artefacts")
    return "\n".join(lines)


_TERMINATION_PHRASES = {
    "max-iterations": "iteration cap reached",
    "no-improvement-window": "no improvement within the window",
    "stepper-stopped": "the stepper stopped the search",
    "defect": "a defect aborted the search (history through the last scored iteration is kept)",
}


def render_optimization_run(
    contract_id: str,
    run_id: str,
    samples_per_iteration: int,
    iterations: Sequence[tuple[int, float, int, int]],
    termination: str,
    best_index: int,
    best_factors: Mapping[str, object],
    artefact_path: str,
) -> str:
    """Render one optimize run's summary: descriptive, one line per iteration.

    Each iterations entry is ``(index, score, successes, samples)``. No
    verdict vocabulary appears anywhere: an optimize run records what each
    configuration scored; judging the winner is a test's job — after the
    winning values are folded into the baseline and re-measured.
    """
    count = len(iterations)
    plural = "" if count == 1 else "s"
    lines = [
        f"contract {contract_id}: optimization {run_id!r} ran {count} "
        f"iteration{plural}, {samples_per_iteration} sample(s) each "
        "(descriptive — an optimize run renders no verdict)"
    ]
    for index, score, successes, samples in iterations:
        marker = "  ← best" if index == best_index else ""
        lines.append(
            f"  iteration {index}: score {score:.4f} "
            f"({successes} of {samples} responses met expectations){marker}"
        )
    lines.append(f"  stopped: {_TERMINATION_PHRASES.get(termination, termination)}")
    lines.append(f"  best factors (iteration {best_index}):")
    for key, value in best_factors.items():
        lines.append(f"    {key}: {value}")
    lines.append(f"  artefact: {artefact_path}")
    lines.append(
        "  promote the winner by folding its values into the `configuration:` "
        "block, then re-measure"
    )
    return "\n".join(lines)


def render_refusal(contract_name: str, error: ConfigurationRefusedError) -> str:
    """Render the constructive refusal of a configuration refused before any sample ran.

    Every applicable code is named, in the fixed order, so every part can
    be corrected at once.
    """
    codes = " ".join(error.errors)
    lines = [f"contract {contract_name}: configuration refused before any sample ran ({codes})"]
    for part in error.parts:
        if part.code is ConfigurationError.TEST_LARGER_THAN_BASELINE:
            lines.append(
                f"  TEST_LARGER_THAN_BASELINE: {part.subject} — the test is planned at "
                f"{part.planned_samples} samples, larger than its baseline run of "
                f"{part.limit}; a baseline must be at least as large as any test that "
                "consumes it. Run at most "
                f"{part.limit} samples, or measure a larger baseline."
            )
        else:
            lines.append(
                f"  COMPLIANCE_INFEASIBLE: {part.subject} — no outcome of "
                f"{part.planned_samples} samples can demonstrate {part.requirement:g}; a pass "
                f"is possible from {part.limit} samples. Raise the sample count, or declare "
                "`intent: smoke` for a sentinel check that reports PASS is not possible."
            )
    return "\n".join(lines)
