"""The service-contract model: what a probabilistic test or measurement runs against.

A service contract names a stochastic service, knows how to invoke it, and
declares the criteria its responses are judged by. Each criterion is its own
Bernoulli stream over the run's samples: it owns its postconditions, an
optional transformation of the raw response into the value under judgement,
and -- when the criterion is normative -- a declared pass-rate threshold with
its confidence level.

This package is a pure domain model plus per-trial evaluation. It has no
third-party dependencies and performs no I/O; sampling loops, statistics
aggregation, persistence, and rendering live in their own packages and
depend on this one, never the reverse.

Contracts hold plain callables for invocation and transformation. Where those
callables come from -- hand-written code, or resolution from a contract file's
registries -- is deliberately outside this package's knowledge: a
hand-authored contract and one instantiated from a contract file are the same
type.
"""

from .evaluation import (
    CriterionTally,
    Outcome,
    TrialDefectError,
    TrialEvaluation,
    TrialViews,
    evaluate_trial,
)
from .model import (
    PERCENTILE_LEVELS,
    Criterion,
    LatencyBar,
    LatencyBound,
    ServiceContract,
    ServiceDeliveryError,
    ThresholdProvenance,
    TransformError,
)
from .postconditions import (
    Postcondition,
    PostconditionResult,
    contains,
    equals,
    matches,
    one_of,
    satisfies,
)

__all__ = [
    "PERCENTILE_LEVELS",
    "Criterion",
    "LatencyBar",
    "LatencyBound",
    "CriterionTally",
    "Outcome",
    "Postcondition",
    "PostconditionResult",
    "ServiceContract",
    "ServiceDeliveryError",
    "ThresholdProvenance",
    "TransformError",
    "TrialDefectError",
    "TrialEvaluation",
    "TrialViews",
    "contains",
    "equals",
    "evaluate_trial",
    "matches",
    "one_of",
    "satisfies",
]
