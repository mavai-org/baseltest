"""Renderers: turning run results into human-facing output.

Renderers format pre-computed results; they never compute statistics.
The console renderer implements the family's honest-output discipline:
a thresholded run renders per-criterion verdicts and a composite with
uncertainty stated; a run without thresholds is labelled a measurement
and uses no verdict vocabulary.
"""

from .console import bar_standing, render_infeasible, render_run
from .html import render_html_report

__all__ = ["render_html_report", "bar_standing", "render_infeasible", "render_run"]
