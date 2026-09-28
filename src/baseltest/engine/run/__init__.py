"""Run execution: preflight, sampling loop, judgement, the test verdict.

The package's public surface is re-exported here; its concerns live in sibling
modules — ``model`` (the value types and vocabulary), ``feasibility``,
``identity``, ``judge``, ``standing``, and ``execute`` (the sampling loop).
"""

from .attainment import BarAttainment, bar_attainment
from .execute import execute
from .feasibility import ConfigurationRefusedError, derive_minimum_samples, refused_parts
from .identity import inputs_fingerprint
from .model import (
    CriterionResult,
    Decision,
    Intent,
    PowerDisclosure,
    RefusedPart,
    RunKind,
    RunPlan,
    RunResult,
    SampleRecord,
)

__all__ = [
    "BarAttainment",
    "ConfigurationRefusedError",
    "CriterionResult",
    "Decision",
    "Intent",
    "PowerDisclosure",
    "RefusedPart",
    "RunKind",
    "RunPlan",
    "RunResult",
    "SampleRecord",
    "bar_attainment",
    "derive_minimum_samples",
    "execute",
    "inputs_fingerprint",
    "refused_parts",
]
