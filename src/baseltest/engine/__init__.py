"""The sampling engine: drive a contract N times and produce the run result.

The engine owns the run lifecycle -- feasibility preflight, the sampling
loop, per-criterion verdicts via the statistics package, and the composite
verdict -- and nothing else: it neither parses task files nor renders
output nor persists artefacts. It consumes the contract model and the
statistics package; everything downstream consumes its
:class:`~baseltest.engine.run.RunResult` without recomputing.
"""

from baseltest.statistics.verdict import Verdict

from .run import (
    CriterionResult,
    InfeasibleCriterion,
    InfeasibleRunError,
    Intent,
    RunKind,
    RunPlan,
    RunResult,
    bar_standing,
    derive_minimum_samples,
    execute,
    inputs_fingerprint,
)

__all__ = [
    "CriterionResult",
    "InfeasibleCriterion",
    "InfeasibleRunError",
    "Intent",
    "RunKind",
    "RunPlan",
    "RunResult",
    "Verdict",
    "bar_standing",
    "derive_minimum_samples",
    "execute",
    "inputs_fingerprint",
]
