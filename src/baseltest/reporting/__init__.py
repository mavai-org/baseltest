"""Renderers: turning run results into human-facing output.

Renderers format pre-computed results; they never compute statistics.
The console renderer implements the family's honest-output discipline:
a thresholded run renders per-criterion verdicts and a composite with
uncertainty stated; a run without thresholds is labelled a measurement
and uses no verdict vocabulary.
"""

from .console import bar_standing, render_infeasible, render_run
from .html import render_html_report
from .verdict_xml import render_verdict_record, write_verdict_record

__all__ = [
    "bar_standing",
    "render_html_report",
    "render_infeasible",
    "render_run",
    "render_verdict_record",
    "write_verdict_record",
]
