"""The probabilistic-test summary: one test run, one self-contained page.

This is the family's test-summary report, and deliberately nothing else: a
measure run's product is its baseline artefact (it has no HTML report in
the family), and exploration/optimisation reports arrive with their seams.
Zero-dependency by philosophy and styled in the family's shared report
design language: CSS custom properties for the verdict colours, a light
page with white panels, definition-list criterion blocks, and native
``details``/``summary`` drill-down. No template engine, no JavaScript, no
external assets; every number comes from the pre-computed run result.
"""

import html
from datetime import UTC, datetime

from baseltest.engine import CriterionResult, RunKind, RunResult, Verdict

_STYLE = """
:root {
    --pass-color: #2e7d32;
    --fail-color: #c62828;
    --inconclusive-color: #6a1b9a;
    --border-color: #dee2e6;
    --bg-light: #f8f9fa;
    --bg-white: #ffffff;
    --text-color: #212529;
    --text-muted: #6c757d;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: var(--text-color);
    background: var(--bg-light);
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}
header { margin-bottom: 2rem; }
h1 { font-size: 1.75rem; margin-bottom: 0.5rem; }
h1 code { font-size: 1.5rem; }
.timestamp { color: var(--text-muted); font-size: 0.875rem; }
.summary-stats {
    margin-top: 1rem;
    display: flex;
    gap: 1.5rem;
    font-size: 1rem;
    font-weight: 600;
}
.stat { padding: 0.25rem 0.75rem; border-radius: 4px; background: var(--bg-white);
        border: 1px solid var(--border-color); }
.punit-pass { color: var(--pass-color); font-weight: 600; }
.punit-fail { color: var(--fail-color); font-weight: 600; }
.punit-inconclusive { color: var(--inconclusive-color); font-weight: 600; }
.criterion-block {
    background: var(--bg-white);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
}
.criterion-block h4 {
    font-size: 0.875rem;
    font-family: monospace;
    margin-bottom: 0.25rem;
}
.criterion-block dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    column-gap: 1rem;
    row-gap: 0.1rem;
    font-size: 0.8125rem;
    margin-left: 0.5rem;
}
.criterion-block dt { color: var(--text-muted); }
.criterion-block dd { font-family: monospace; }
details > summary { cursor: pointer; font-weight: 500; font-size: 0.8125rem;
                    margin-top: 0.5rem; }
details > summary:hover { text-decoration: underline; }
table.postcondition-failures {
    margin: 0.5rem 0 0.5rem 1.5rem;
    border-collapse: collapse;
    font-size: 0.8125rem;
    background: var(--bg-white);
}
table.postcondition-failures th,
table.postcondition-failures td {
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border-color);
    text-align: left;
}
footer { margin-top: 1.5rem; color: var(--text-muted); font-size: 0.8125rem;
         border-top: 1px solid var(--border-color); padding-top: 0.6rem; }
"""


def _verdict_class(verdict: Verdict | None) -> str:
    if verdict is Verdict.PASS:
        return "punit-pass"
    if verdict is Verdict.FAIL:
        return "punit-fail"
    return "punit-inconclusive"


def _criterion_block(result: CriterionResult) -> str:
    tally = result.tally
    criterion = result.criterion
    if result.verdict is not None:
        status = (
            f'<span class="{_verdict_class(result.verdict)}">{result.verdict.value.upper()}</span>'
        )
    else:
        status = '<span class="timestamp">measured (no threshold declared)</span>'
    rows = [
        ("observed", f"{tally.successes}/{tally.trials} ({tally.observed_rate:.4f})"),
    ]
    if result.verdict is not None and result.lower_bound is not None:
        assert criterion.threshold is not None
        rows.append(
            (
                f"{criterion.confidence:.0%} lower bound",
                f"{result.lower_bound:.4f} vs threshold {criterion.threshold}",
            )
        )
        if criterion.provenance.contract_ref is not None:
            rows.append(
                (
                    "threshold origin",
                    f"{criterion.provenance.origin}, {criterion.provenance.contract_ref}",
                )
            )
    else:
        variance = tally.observed_rate * (1 - tally.observed_rate)
        rows.append(("variance", f"{variance:.4f}"))
    definitions = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>" for label, value in rows
    )
    failure_details = ""
    if tally.failure_reasons:
        failure_rows = "".join(
            f"<tr><td>{count}</td><td>{html.escape(reason)}</td></tr>"
            for reason, count in tally.failure_reasons.most_common()
        )
        failure_details = (
            "<details><summary>failure distribution "
            f"({sum(tally.failure_reasons.values())} failed trials)</summary>"
            '<table class="postcondition-failures">'
            "<thead><tr><th>count</th><th>reason</th></tr></thead>"
            f"<tbody>{failure_rows}</tbody></table></details>"
        )
    return (
        '<div class="criterion-block">'
        f"<h4>{html.escape(result.name)} {status}</h4>"
        f"<dl>{definitions}</dl>{failure_details}</div>"
    )


def render_html_report(result: RunResult) -> str:
    """Render the test-summary page for one probabilistic test run.

    Raises:
        ValueError: For a non-test run — a measurement's product is its
            baseline artefact, not a report.
    """
    if result.kind is not RunKind.TEST or result.composite is None:
        raise ValueError(
            "the HTML report is the probabilistic-test summary; a measure or "
            "observation run has no report — its product is the baseline artefact"
        )
    headline = (
        f'<span class="{_verdict_class(result.composite)}">{result.composite.value.upper()}</span>'
    )
    blocks = "".join(_criterion_block(r) for r in result.criterion_results)
    generated = datetime.now(tz=UTC).isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(result.contract_id)} — baseltest report</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
<h1><code>{html.escape(result.contract_id)}</code> {headline}</h1>
<p class="timestamp">started {result.started_at.isoformat(timespec="seconds")}</p>
<div class="summary-stats">
<span class="stat">{result.plan.samples} samples</span>
<span class="stat">mode: {result.kind.value}</span>
<span class="stat">{len(result.criterion_results)} criteria</span>
</div>
</header>
{blocks}
<footer>generated {generated} · inputs identity
<code>{html.escape(result.inputs_identity[:16])}…</code> · baseltest</footer>
</body>
</html>
"""
