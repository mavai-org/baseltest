"""Renderers: turning run results into human-facing output.

Renderers format pre-computed results; they never compute statistics.
The console renderer implements the family's honest-output discipline:
a thresholded run renders per-criterion verdicts and a composite with
uncertainty stated; a run without thresholds is labelled a measurement
and uses no verdict vocabulary.

**No HTML is rendered here.** The console and the verdict record are what
this package produces; a reader's report is mavai's to render, from the
persisted artefacts, for the whole family at once.
"""

from .console import (
    render_explorations,
    render_infeasible,
    render_optimization_run,
    render_run,
    render_run_plan,
)
from .run_design import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    SizingDisclosure,
)
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
    "parse_verdict_record",
    "read_verdict_directory",
    "render_explorations",
    "render_infeasible",
    "render_optimization_run",
    "render_run",
    "render_run_plan",
    "render_verdict_record",
    "write_verdict_record",
]
