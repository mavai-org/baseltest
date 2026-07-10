"""The HTML test report: the family's report structure over verdict records.

Structure and styling follow the family's reference renderer to the letter:
header with summary stats and an attention banner when inconclusives exist,
a collapsed statistical-assumptions block, one section per contract with
the columns Test Name | Verdict | Functional | p50 | p95 | p99 | Samples |
Elapsed, and per-row ``<details>`` drill-down (summary text, statistical
analysis, per-criterion breakdown, postcondition failures). A renderer:
every number is read from the parsed record, never computed here.
"""

from .report_html import document_head, escape, footer, timestamp, verdict_css_class
from .verdict_reader import LatencyRecord, VerdictRecord

_STATUS_CLASS = {"PASS": "latency-pass", "STRICT_FAIL": "latency-fail", "INFEASIBLE": "muted"}


def render_test_report(records: list[VerdictRecord]) -> str:
    """Render the parsed verdict records as one self-contained HTML page."""
    generated = timestamp()
    passed = sum(1 for r in records if r.verdict == "PASS")
    failed = sum(1 for r in records if r.verdict == "FAIL")
    inconclusive = sum(1 for r in records if r.verdict == "INCONCLUSIVE")

    html = [document_head("basel Test Report")]
    html.append("<header>\n<h1>basel Test Report</h1>\n")
    html.append(f'<p class="timestamp">Generated: {escape(generated)}</p>\n')
    html.append('<div class="summary-stats">\n')
    html.append(f'<span class="stat">Total: {len(records)}</span>\n')
    html.append(f'<span class="stat basel-pass">Pass: {passed}</span>\n')
    html.append(f'<span class="stat basel-fail">Fail: {failed}</span>\n')
    if inconclusive:
        html.append(f'<span class="stat basel-inconclusive">Inconclusive: {inconclusive}</span>\n')
    html.append("</div>\n")
    if inconclusive:
        plural = "test has" if inconclusive == 1 else "tests have"
        html.append(
            '<div class="banner-inconclusive">\n<strong>Attention:</strong> '
            f"{inconclusive} {plural} an inconclusive verdict: too few samples passed "
            "for an asserted latency percentile to be estimated. Re-run with a larger "
            "budget: <code>basel test &lt;contract&gt; --samples N</code>\n</div>\n"
        )
    html.append("</header>\n")

    _append_assumptions(html)

    html.append("<main>\n")
    for contract_id in dict.fromkeys(r.contract_id for r in records):
        html.append('<section class="test-group">\n')
        html.append(f"<h2>{escape(contract_id)}</h2>\n")
        html.append("<table>\n<thead>\n<tr>\n")
        html.append(
            "<th>Test Name</th><th>Verdict</th><th>Functional</th><th>p50</th>"
            "<th>p95</th><th>p99</th><th>Samples</th><th>Elapsed</th>"
        )
        html.append("</tr>\n</thead>\n<tbody>\n")
        for record in records:
            if record.contract_id == contract_id:
                _append_row(html, record)
        html.append("</tbody>\n</table>\n</section>\n")
    html.append("</main>\n")
    html.append(footer(generated))
    return "".join(html)


def _append_row(html: list[str], record: VerdictRecord) -> None:
    html.append("<tr>\n<td>\n<details>\n")
    html.append(f"<summary>{escape(record.contract_id)}</summary>\n")
    html.append(f'<pre class="level2">{escape(_summary_text(record))}</pre>\n')
    _append_per_criterion(html, record)
    _append_latency_detail(html, record.latency)
    _append_clauses(html, record)
    html.append("</details>\n</td>\n")

    html.append(f'<td class="{verdict_css_class(record.verdict)}">{record.verdict}</td>\n')
    total = record.successes + record.failures
    html.append(f"<td>{record.successes}/{total}</td>\n")
    for label in ("p50", "p95", "p99"):
        observed = record.latency.observed_ms(label) if record.latency is not None else None
        cell = "-" if observed is None else f"{observed}ms"
        html.append(f'<td class="latency-observed">{cell}</td>\n')
    html.append(f"<td>{record.planned_samples}/{record.planned_samples}</td>\n")
    html.append(f"<td>{record.elapsed_ms}ms</td>\n")
    html.append("</tr>\n")


def _summary_text(record: VerdictRecord) -> str:
    lines = [
        f"verdict: {record.verdict} (intent {record.intent}, confidence {record.confidence:g})"
    ]
    if record.wilson_lower is not None and record.statistics_threshold is not None:
        lines.append(
            f"wilson lower bound {record.wilson_lower:.4f} against "
            f"threshold {record.statistics_threshold:g} (origin {record.origin})"
        )
    if record.contract_ref is not None:
        lines.append(f"contract ref: {record.contract_ref}")
    return "\n".join(lines)


def _append_per_criterion(html: list[str], record: VerdictRecord) -> None:
    if not record.criteria:
        return
    html.append("<details>\n<summary>Per-criterion breakdown</summary>\n")
    html.append('<div class="per-criterion">\n')
    for row in record.criteria:
        html.append('<div class="criterion-block">\n')
        html.append(
            f"<h4>{escape(row.criterion_id)} "
            f'<span class="{verdict_css_class(row.verdict)}">{row.verdict}</span></h4>\n'
        )
        html.append("<dl>\n")
        html.append(f"<dt>Pass</dt><dd>{row.passes}</dd>\n")
        html.append(f"<dt>Fail</dt><dd>{row.fails}</dd>\n")
        html.append(f"<dt>Total</dt><dd>{row.total}</dd>\n")
        html.append(f"<dt>Observed rate</dt><dd>{row.observed_rate:.4f}</dd>\n")
        if row.threshold is not None:
            html.append(f"<dt>Threshold</dt><dd>{row.threshold:.4f}</dd>\n")
        html.append("</dl>\n</div>\n")
    html.append("</div>\n</details>\n")


def _append_latency_detail(html: list[str], latency: LatencyRecord | None) -> None:
    if latency is None or not latency.evaluations:
        return
    html.append("<details>\n<summary>Latency evaluation</summary>\n")
    html.append('<div class="per-criterion">\n<div class="criterion-block">\n<dl>\n')
    for row in latency.evaluations:
        observed = "-" if row.observed_ms is None else f"{row.observed_ms}ms"
        status_class = _STATUS_CLASS.get(row.status, "muted")
        detail = f"observed {observed}, bound {row.threshold_ms}ms ({row.provenance})"
        if row.baseline_rank is not None and row.baseline_n is not None:
            detail += f", rank {row.baseline_rank} of {row.baseline_n}"
        if row.baseline_confidence is not None:
            detail += f" at confidence {row.baseline_confidence:g}"
        html.append(
            f"<dt>{escape(row.percentile)}</dt>"
            f'<dd><span class="{status_class}">{row.status}</span> — {escape(detail)}</dd>\n'
        )
    html.append("</dl>\n</div>\n</div>\n</details>\n")


def _append_clauses(html: list[str], record: VerdictRecord) -> None:
    if not record.clauses:
        return
    html.append("<details>\n<summary>Postcondition Failures</summary>\n")
    html.append('<table class="postcondition-failures">\n')
    html.append("<thead><tr><th>Clause</th><th>Count</th></tr></thead>\n<tbody>\n")
    for description, count in record.clauses:
        html.append(
            f'<tr>\n<td class="clause">{escape(description)}</td>\n'
            f'<td class="count">{count}</td>\n</tr>\n'
        )
    html.append("</tbody>\n</table>\n</details>\n")


def _append_assumptions(html: list[str]) -> None:
    html.append('<details class="assumptions">\n')
    html.append("<summary>Statistical assumptions and limitations</summary>\n")
    html.append('<div class="assumptions-body">\n')
    html.append(
        "<p>This report uses statistical methods that assume repeated executions can be "
        "treated as comparable pass/fail trials. That is not automatically true for every "
        "test. If the test itself changes the state, performance, or behaviour of the "
        "system from one run to the next, the resulting figures may be mathematically "
        "correct yet statistically misleading. In such cases, the report should be read "
        "as a rough signal only, not as a reliable probabilistic assessment.</p>\n"
    )
    html.append(
        "<p>The statistics in this report are valid when the following "
        "assumptions hold:</p>\n<ul>\n"
    )
    html.append(
        "<li><strong>Binary outcome</strong> &mdash; each run has a clear and "
        "consistent pass/fail result.</li>\n"
    )
    html.append(
        "<li><strong>Same question each time</strong> &mdash; repeated runs are "
        "testing the same condition.</li>\n"
    )
    html.append(
        "<li><strong>Unchanged threshold</strong> &mdash; the success criterion "
        "remains the same throughout.</li>\n"
    )
    html.append(
        "<li><strong>Independence</strong> &mdash; earlier runs do not "
        "substantially influence later ones.</li>\n"
    )
    html.append(
        "<li><strong>No major drift during sampling</strong> &mdash; the underlying "
        "behaviour is reasonably stable over the sample window.</li>\n</ul>\n"
    )
    html.append(
        '<p class="assumptions-warning"><strong>Warning:</strong> tests that warm up, '
        "exhaust, mutate, learn, cache, throttle, or degrade the target can violate these "
        "assumptions and weaken the meaning of the statistics.</p>\n"
    )
    html.append("</div>\n</details>\n")
