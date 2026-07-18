"""The sampling engine: drive a contract N times and produce the run result.

The engine owns the run lifecycle -- feasibility preflight, the sampling
loop, per-criterion verdicts via the statistics package, and the composite
verdict -- and nothing else: it neither parses contract files nor renders
output nor persists artefacts. It consumes the contract model and the
statistics package; everything downstream consumes its
:class:`~baseltest.engine.run.RunResult` without recomputing.
"""

from baseltest.statistics.verdict import Verdict

from .defect import TRANSFORM_CONTRACT_NOTE, DefectDiagnosisError
from .latency import (
    BoundEvaluation,
    LatencyBlock,
    LatencyEvaluation,
    evaluate_latency,
    latency_block,
    minimum_contributing_samples,
)
from .run import (
    CriterionResult,
    InfeasibleCriterion,
    InfeasibleRunError,
    Intent,
    RunKind,
    RunPlan,
    RunResult,
    SampleRecord,
    bar_standing,
    derive_minimum_samples,
    execute,
    inputs_fingerprint,
)

__all__ = [
    "TRANSFORM_CONTRACT_NOTE",
    "BoundEvaluation",
    "CriterionResult",
    "DefectDiagnosisError",
    "LatencyEvaluation",
    "InfeasibleCriterion",
    "InfeasibleRunError",
    "Intent",
    "LatencyBlock",
    "RunKind",
    "RunPlan",
    "RunResult",
    "SampleRecord",
    "Verdict",
    "bar_standing",
    "derive_minimum_samples",
    "evaluate_latency",
    "execute",
    "inputs_fingerprint",
    "latency_block",
    "minimum_contributing_samples",
]
