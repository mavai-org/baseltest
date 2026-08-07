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

from .errors import BaseltestError, ContractValidationError, PreconditionError
from .evaluation import (
    CriterionTally,
    EvaluationContext,
    FailureAxis,
    ObservedValue,
    Outcome,
    PostconditionStanding,
    TrialDefectError,
    TrialEvaluation,
    TrialViews,
    evaluate_trial,
)
from .model import (
    PERCENTILE_LEVELS,
    Criterion,
    DeliveryCause,
    FileInput,
    LatencyBar,
    LatencyBound,
    MediaKind,
    MessageParts,
    OptionalSlack,
    ServiceContract,
    ServiceDeliveryError,
    ThresholdProvenance,
    TransformError,
)
from .postconditions import (
    Postcondition,
    PostconditionResult,
    contains,
    contains_set,
    count_equals,
    eq,
    equals,
    equals_ci,
    equals_set,
    ge,
    gt,
    is_,
    is_null,
    le,
    lt,
    matches,
    ne,
    not_equals,
    one_of,
    satisfies,
    set_of,
)
from .reply import Reply

__all__ = [
    "FailureAxis",
    "Reply",
    "PERCENTILE_LEVELS",
    "BaseltestError",
    "ContractValidationError",
    "Criterion",
    "FileInput",
    "LatencyBar",
    "LatencyBound",
    "MediaKind",
    "MessageParts",
    "CriterionTally",
    "OptionalSlack",
    "Outcome",
    "PreconditionError",
    "Postcondition",
    "PostconditionResult",
    "ObservedValue",
    "PostconditionStanding",
    "ServiceContract",
    "DeliveryCause",
    "ServiceDeliveryError",
    "ThresholdProvenance",
    "TransformError",
    "TrialDefectError",
    "TrialEvaluation",
    "EvaluationContext",
    "TrialViews",
    "contains",
    "contains_set",
    "count_equals",
    "eq",
    "equals",
    "equals_ci",
    "equals_set",
    "evaluate_trial",
    "ge",
    "gt",
    "is_",
    "is_null",
    "le",
    "lt",
    "matches",
    "ne",
    "not_equals",
    "one_of",
    "satisfies",
    "set_of",
]
