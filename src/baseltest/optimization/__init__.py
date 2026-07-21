"""The optimization artefact: one record per Optimize experiment run.

An optimize run iteratively searches a service's configuration space and
writes one YAML artefact per run, in the mavai family's optimization
schema (``mavai-optimize-1``). The artefact *is* the full iteration
history — every configuration tried, its score, and its descriptive
statistics — plus the convergence summary naming the selected optimum.
Like exploration, optimization is descriptive: scores and rates are
observed values; no inferential claim is made about the optimum.
"""

from .record import (
    IterationCapture,
    Objective,
    OptimizationRecord,
    Termination,
    wire_scorer_name,
)
from .writer import render_optimization, write_optimization

__all__ = [
    "IterationCapture",
    "Objective",
    "OptimizationRecord",
    "Termination",
    "render_optimization",
    "wire_scorer_name",
    "write_optimization",
]
