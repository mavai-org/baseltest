"""Run execution: preflight, sampling loop, judgement, composite.

The package's public surface is re-exported here; its concerns live in sibling
modules — ``model`` (the value types and vocabulary), ``feasibility``,
``identity``, ``judge``, ``standing``, and ``execute`` (the sampling loop).
"""

from .attainment import BarAttainment, bar_attainment
from .execute import execute
from .feasibility import InfeasibleRunError, derive_minimum_samples
from .identity import inputs_fingerprint
from .model import (
    CriterionResult,
    InfeasibleCriterion,
    Intent,
    RunKind,
    RunPlan,
    RunResult,
    SampleRecord,
)

__all__ = [
    "BarAttainment",
    "CriterionResult",
    "InfeasibleCriterion",
    "InfeasibleRunError",
    "Intent",
    "RunKind",
    "RunPlan",
    "RunResult",
    "SampleRecord",
    "bar_attainment",
    "derive_minimum_samples",
    "execute",
    "inputs_fingerprint",
]
