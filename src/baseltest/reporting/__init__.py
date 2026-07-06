"""Renderers: turning run results into human-facing output.

Renderers format pre-computed results; they never compute statistics.
The console renderer implements the family's honest-output discipline:
a thresholded run renders per-criterion verdicts and a composite with
uncertainty stated; a run without thresholds is labelled a measurement
and uses no verdict vocabulary.
"""

from .console import render_infeasible, render_run

__all__ = ["render_infeasible", "render_run"]
