"""The single-file HTML report: one run, one self-contained page.

Zero-dependency by philosophy (shared with the family's other report
tooling): no template engine, no JavaScript, no external assets — inline
CSS, native ``details``/``summary`` for drill-down, and plain markup. The
report renders pre-computed results only; every number comes from the run
result.
"""

import html
from datetime import UTC, datetime

from baseltest.engine import CriterionResult, RunResult, Verdict

_STYLE = """
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 46rem;
         color: #1a1a1a; line-height: 1.5; }
  h1 { font-size: 1.3rem; } h1 code { font-size: 1.1rem; }
  .verdict { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 0.3rem;
             font-weight: 600; }
  .pass { background: #e6f4e6; color: #1d6b1d; }
  .fail { background: #fbe7e7; color: #a11212; }
  .observation { background: #eef2f7; color: #2c4a6e; }
  .criterion { border: 1px solid #ddd; border-radius: 0.4rem; padding: 0.8rem 1rem;
               margin: 0.8rem 0; }
  .criterion h2 { font-size: 1.05rem; margin: 0 0 0.4rem; }
  .figures { color: #444; margin: 0.2rem 0; }
  .bar { background: #eee; border-radius: 0.2rem; height: 0.6rem; margin: 0.4rem 0; }
  .bar > div { background: #4a7fb5; height: 100%; border-radius: 0.2rem; }
  details { margin-top: 0.5rem; } summary { cursor: pointer; color: #555; }
  table { border-collapse: collapse; margin-top: 0.4rem; }
  td { padding: 0.15rem 0.6rem 0.15rem 0; color: #444; vertical-align: top; }
  footer { margin-top: 1.5rem; color: #777; font-size: 0.85rem;
           border-top: 1px solid #eee; padding-top: 0.6rem; }
"""


def _verdict_chip(result: CriterionResult) -> str:
    if result.verdict is None:
        return '<span class="verdict observation">measured</span>'
    css = "pass" if result.verdict is Verdict.PASS else "fail"
    return f'<span class="verdict {css}">{result.verdict.value.upper()}</span>'


def _criterion_section(result: CriterionResult) -> str:
    tally = result.tally
    criterion = result.criterion
    rate_percent = tally.observed_rate * 100
    parts = [
        '<section class="criterion">',
        f"<h2>{html.escape(result.name)} {_verdict_chip(result)}</h2>",
        f'<p class="figures">{tally.successes} of {tally.trials} responses met '
        f"expectations (observed rate {tally.observed_rate:.4f})</p>",
        f'<div class="bar" role="img" aria-label="observed rate {rate_percent:.1f}%">'
        f'<div style="width:{rate_percent:.1f}%"></div></div>',
    ]
    if result.verdict is not None and result.lower_bound is not None:
        assert criterion.threshold is not None
        relation = "clears" if result.verdict is Verdict.PASS else "falls below"
        source = ""
        if criterion.provenance.contract_ref is not None:
            source = (
                f" ({html.escape(criterion.provenance.origin)}, "
                f"{html.escape(criterion.provenance.contract_ref)})"
            )
        parts.append(
            f'<p class="figures">{criterion.confidence:.0%}-confident lower bound '
            f"<strong>{result.lower_bound:.4f}</strong> {relation} the declared "
            f"threshold <strong>{criterion.threshold}</strong>{source}</p>"
        )
    else:
        variance = tally.observed_rate * (1 - tally.observed_rate)
        parts.append(
            f'<p class="figures">measurement only — no threshold declared '
            f"(variance {variance:.4f})</p>"
        )
    if tally.failure_reasons:
        rows = "".join(
            f"<tr><td>{count}</td><td>{html.escape(reason)}</td></tr>"
            for reason, count in tally.failure_reasons.most_common()
        )
        parts.append(
            "<details><summary>failure distribution "
            f"({sum(tally.failure_reasons.values())} failed trials)</summary>"
            f"<table>{rows}</table></details>"
        )
    parts.append("</section>")
    return "".join(parts)


def render_html_report(result: RunResult, baseline_path: str | None = None) -> str:
    """Render a complete, self-contained HTML page for one run."""
    if result.composite is not None:
        css = "pass" if result.composite is Verdict.PASS else "fail"
        headline = f'<span class="verdict {css}">{result.composite.value.upper()}</span>'
    else:
        headline = (
            '<span class="verdict observation">OBSERVATION — a measurement, not a verdict</span>'
        )
    sections = "".join(_criterion_section(r) for r in result.criterion_results)
    baseline_note = (
        f"<p>baseline written: <code>{html.escape(baseline_path)}</code></p>"
        if baseline_path
        else ""
    )
    generated = datetime.now(tz=UTC).isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(result.contract_id)} — baseltest report</title>
<style>{_STYLE}</style>
</head>
<body>
<h1><code>{html.escape(result.contract_id)}</code> {headline}</h1>
<p class="figures">{result.plan.samples} samples · kind: {result.kind.value}
· started {result.started_at.isoformat(timespec="seconds")}</p>
{sections}
{baseline_note}
<footer>generated {generated} · inputs identity
<code>{html.escape(result.inputs_identity[:16])}…</code> · baseltest</footer>
</body>
</html>
"""
