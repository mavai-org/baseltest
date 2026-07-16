"""Renderers: turning run results into human-facing output.

Renderers format pre-computed results; they never compute statistics.
The console renderer implements the family's honest-output discipline:
a thresholded run renders per-criterion verdicts and a composite with
uncertainty stated; a run without thresholds is labelled a measurement
and uses no verdict vocabulary.
"""

from baseltest.engine import bar_standing

from .console import render_explorations, render_infeasible, render_run, render_run_plan
from .run_design import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    SizingDisclosure,
)
from .test_report import render_test_report
from .verdict_reader import (
    VerdictRecord,
    VerdictSweep,
    parse_verdict_record,
    read_verdict_directory,
)
from .verdict_xml import render_verdict_record, write_verdict_record

__all__ = [
    "RISK_DRIVEN_APPROACH",
    "BaselineDisclosure",
    "ClaimDisclosure",
    "RunDesign",
    "SizingDisclosure",
    "VerdictRecord",
    "VerdictSweep",
    "bar_standing",
    "parse_verdict_record",
    "read_verdict_directory",
    "render_explorations",
    "render_infeasible",
    "render_run",
    "render_run_plan",
    "render_test_report",
    "render_verdict_record",
    "write_verdict_record",
]
