"""The sampling engine: drive a contract N times and produce the run result.

The engine owns the run lifecycle -- the configuration preflight, the
sampling loop, per-criterion decisions via the statistics package, and the
test verdict -- and nothing else: it neither parses contract files nor renders
output nor persists artefacts. It consumes the contract model and the
statistics package; everything downstream consumes its
:class:`~baseltest.engine.run.RunResult` without recomputing.
"""

from baseltest.statistics import (
    METHODOLOGY_VERSION,
    ComplianceVerdict,
    ConfigurationError,
    Dimension,
    EnforcementMode,
    Envelopes,
    RegressionVerdict,
    Verdict,
)

from .defect import TRANSFORM_CONTRACT_NOTE, DefectDiagnosisError
from .latency import (
    BoundEvaluation,
    LatencyBasis,
    LatencyBlock,
    LatencyEvaluation,
    LatencyPlanning,
    evaluate_latency,
    latency_block,
    minimum_contributing_samples,
    plan_latency,
)
from .run import (
    BarAttainment,
    ConfigurationRefusedError,
    CriterionResult,
    Decision,
    Intent,
    PowerDisclosure,
    RefusedPart,
    RunKind,
    RunPlan,
    RunResult,
    SampleRecord,
    bar_attainment,
    derive_minimum_samples,
    execute,
    inputs_fingerprint,
    refused_parts,
)

__all__ = [
    "METHODOLOGY_VERSION",
    "TRANSFORM_CONTRACT_NOTE",
    "ComplianceVerdict",
    "ConfigurationError",
    "Dimension",
    "EnforcementMode",
    "Envelopes",
    "RegressionVerdict",
    "BarAttainment",
    "BoundEvaluation",
    "ConfigurationRefusedError",
    "CriterionResult",
    "Decision",
    "LatencyBasis",
    "DefectDiagnosisError",
    "LatencyEvaluation",
    "Intent",
    "LatencyBlock",
    "LatencyPlanning",
    "PowerDisclosure",
    "RefusedPart",
    "RunKind",
    "RunPlan",
    "RunResult",
    "SampleRecord",
    "Verdict",
    "bar_attainment",
    "derive_minimum_samples",
    "evaluate_latency",
    "execute",
    "inputs_fingerprint",
    "latency_block",
    "minimum_contributing_samples",
    "plan_latency",
    "refused_parts",
]
