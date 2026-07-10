"""Shared HTML primitives for the report renderers: escaping, the base
stylesheet, and the document shell.

The stylesheet is the mavai family's report look — colour palette, font
stack, table styling, and the ``<details>``/``<summary>`` idiom — carried
verbatim from the family's reference renderer so every framework's reports
are visually of a piece. Reports are single self-contained files: all CSS
inline, no JavaScript, no external assets; charts are inline SVG and
CSS-width bars only.
"""

from datetime import UTC, datetime

BASE_CSS = """\
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
h2 { font-size: 1.25rem; margin-bottom: 0.75rem; color: var(--text-muted); }
.timestamp { color: var(--text-muted); font-size: 0.875rem; }
.summary-stats {
    margin-top: 1rem;
    display: flex;
    gap: 1.5rem;
    font-size: 1rem;
    font-weight: 600;
}
.stat { padding: 0.25rem 0.75rem; border-radius: 4px; }
table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-white);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    margin-bottom: 1.5rem;
}
thead th {
    background: var(--bg-light);
    padding: 0.75rem;
    text-align: left;
    font-size: 0.875rem;
    border-bottom: 2px solid var(--border-color);
}
tbody td {
    padding: 0.75rem;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.875rem;
    vertical-align: top;
}
tbody tr:last-child td { border-bottom: none; }
details > summary {
    cursor: pointer;
    font-weight: 500;
}
details > summary:hover { text-decoration: underline; }
pre.level2, pre.level3 {
    margin: 0.5rem 0 0.5rem 1.5rem;
    padding: 0.75rem;
    background: var(--bg-light);
    border: 1px solid var(--border-color);
    border-left: 3px solid var(--border-color);
    border-radius: 4px;
    font-size: 0.8125rem;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
}
details details {
    margin-left: 1.5rem;
}
.basel-pass { color: var(--pass-color); font-weight: 600; }
.basel-fail { color: var(--fail-color); font-weight: 600; }
.basel-inconclusive { color: var(--inconclusive-color); font-weight: 600; }
.per-criterion { padding: 0.5rem 0 0.25rem 0.5rem; }
.criterion-block { margin: 0.25rem 0 0.75rem 0; }
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
.latency-observed { color: #adb5bd; }
.latency-pass { color: var(--pass-color); font-weight: 600; }
.latency-fail { color: var(--fail-color); font-weight: 600; }
.test-group { margin-bottom: 2rem; }
.banner-inconclusive {
    margin-top: 1rem;
    padding: 0.75rem 1rem;
    background: #f3e5f5;
    border: 1px solid var(--inconclusive-color);
    border-left: 4px solid var(--inconclusive-color);
    border-radius: 4px;
    font-size: 0.875rem;
    color: var(--text-color);
}
.banner-inconclusive code {
    background: var(--bg-white);
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    font-size: 0.8125rem;
}
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
    vertical-align: top;
    text-align: left;
}
table.postcondition-failures th {
    background: #f8f9fa;
    font-weight: 600;
    color: var(--text-muted);
}
table.postcondition-failures td.clause { font-weight: 500; }
table.postcondition-failures td.count {
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--fail-color);
    font-weight: 600;
}
.assumptions {
    margin-bottom: 1.5rem;
    background: var(--bg-white);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 0.875rem;
}
.assumptions > summary {
    padding: 0.75rem 1rem;
    cursor: pointer;
    font-weight: 600;
    color: var(--text-muted);
}
.assumptions > summary:hover { color: var(--text-color); }
.assumptions-body {
    padding: 0.75rem 1rem 1rem;
    border-top: 1px solid var(--border-color);
    line-height: 1.6;
}
.assumptions-body p { margin-bottom: 0.75rem; }
.assumptions-body ul {
    margin: 0 0 0.75rem 1.5rem;
    list-style-type: disc;
}
.assumptions-body li { margin-bottom: 0.35rem; }
.assumptions-warning {
    padding: 0.5rem 0.75rem;
    background: #fff8e1;
    border-left: 3px solid #f9a825;
    border-radius: 4px;
}
footer {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 0.8125rem;
}
"""

# Chart rules shared with the family's comparison reports: section spacing,
# the tie-mark/tie-legend idiom, the CSS-width bar primitive, badges, the
# factor-list <dl>, and the criterion-matrix cells.
CHART_CSS = """\
h3 { font-size: 1rem; margin: 1rem 0 0.5rem; color: var(--text-color); }
.service { margin-bottom: 2.5rem; }
.overview { margin-bottom: 2rem; }
p.empty { color: var(--text-muted); font-style: italic; }
td.rank, td.num { text-align: right; font-variant-numeric: tabular-nums; }
.tie-mark {
    color: var(--text-muted);
    font-weight: 600;
    margin-left: 0.15rem;
    cursor: help;
}
p.tie-legend {
    margin: -1rem 0 1.5rem;
    padding: 0.5rem 0.75rem;
    background: var(--bg-light);
    border: 1px solid var(--border-color);
    border-left: 3px solid var(--text-muted);
    border-radius: 4px;
    font-size: 0.8125rem;
    color: var(--text-color);
    line-height: 1.5;
}
table.leaderboard td { vertical-align: middle; }
.bar-track {
    position: relative;
    display: inline-block;
    width: 120px;
    height: 0.9rem;
    background: var(--bg-light);
    border: 1px solid var(--border-color);
    border-radius: 3px;
    overflow: hidden;
    vertical-align: middle;
}
.bar-track.narrow { width: 80px; }
.bar-fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
}
.bar-fill.pass { background: var(--pass-color); }
.bar-fill.fail { background: var(--fail-color); }
.bar-fill.muted { background: #adb5bd; }
td.passrate span, td.latency span, td.cost span, td.cell span {
    margin-left: 0.4rem;
    font-variant-numeric: tabular-nums;
    font-size: 0.8125rem;
}
.muted { color: var(--text-muted); }
.badge {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border-radius: 3px;
    font-size: 0.75rem;
    font-weight: 600;
}
.badge.ok { background: #e8f5e9; color: var(--pass-color); }
.badge.warn { background: #fff8e1; color: #b26a00; border: 1px solid #f9a825; }
dl.factor-list {
    display: grid;
    grid-template-columns: max-content 1fr;
    column-gap: 1rem;
    row-gap: 0.25rem;
    margin: 0.5rem 0 0.25rem 0.5rem;
    font-size: 0.8125rem;
}
dl.factor-list dt { color: var(--text-muted); font-family: monospace; }
dl.factor-list dd { margin: 0; }
dl.factor-list pre {
    margin: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 0.8125rem;
}
table.criterion-matrix td.criterion-name { font-family: monospace; font-size: 0.8125rem; }
table.criterion-matrix td.cell, table.criterion-matrix td.cell-na { white-space: nowrap; }
table.latency-strips td { vertical-align: middle; }
table.latency-strips td.strip-label { font-weight: 500; white-space: nowrap; }
svg.latency-strip-svg { vertical-align: middle; }
.strip-axis { stroke: var(--border-color); stroke-width: 1; }
.strip-dot { fill: #6c757d; }
.strip-p50 { stroke: var(--pass-color); stroke-width: 2; }
.strip-range {
    margin-left: 0.5rem;
    font-size: 0.8125rem;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
}
"""


def escape(text: str | None) -> str:
    """Escape the characters unsafe in HTML text and quoted attributes."""
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def timestamp() -> str:
    """The report's human-readable generation time."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S %Z")


def document_head(title: str, extra_css: str = "") -> str:
    """The document shell up to ``</head>``: charset, viewport, title, CSS."""
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>\n{BASE_CSS}{extra_css}</style>\n"
        "</head>\n<body>\n"
    )


def footer(generated: str) -> str:
    """The document tail from ``<footer>`` to ``</html>``."""
    return (
        f"<footer>\n<p>Generated by basel at {escape(generated)}</p>\n</footer>\n</body>\n</html>\n"
    )


def verdict_css_class(verdict: str) -> str:
    """The colour class for a verdict token (PASS / FAIL / INCONCLUSIVE)."""
    return {
        "PASS": "basel-pass",
        "FAIL": "basel-fail",
        "INCONCLUSIVE": "basel-inconclusive",
    }.get(verdict, "basel-inconclusive")
