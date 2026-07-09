"""Pure statistical primitives for probabilistic testing of stochastic services.

This package has no dependency on any other `baseltest` package -- it is a
self-contained library of pure functions and immutable data structures
covering:

- Wilson score confidence intervals (`wilson`)
- Pass-rate threshold derivation, in three directions (`threshold`)
- Power analysis / sample size calculation (`power`)
- Feasibility checking for a test configuration (`feasibility`)
- Verdict evaluation for a single criterion (`verdict`)
- Combined false-positive risk across multiple criteria (`summary`)

Every public name here is validated against the mavai-R statistical oracle
(see `tests/statistics/` in this repository) to a stated numerical
tolerance, and nothing in this package has side effects.
"""

from .feasibility import FeasibilityCheck, check_feasibility
from .latency import (
    LatencyThreshold,
    bound_existence_minimum,
    derive_latency_threshold,
    latency_max,
    latency_mean,
    latency_percentile,
)
from .power import achieved_power, required_sample_size
from .summary import MultiRunSummary, RunOutcome, summarize_runs
from .threshold import (
    ConfidenceFirstThreshold,
    DerivationApproach,
    SampleSizeFirstThreshold,
    ThresholdFirstConfidence,
    derive_confidence_first,
    derive_sample_size_first,
    derive_threshold_first,
)
from .verdict import (
    ComplianceVerdict,
    RegressionVerdict,
    Verdict,
    evaluate_compliance,
    evaluate_regression,
)
from .wilson import (
    WilsonInterval,
    wilson_interval,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)

__all__ = [
    "ComplianceVerdict",
    "ConfidenceFirstThreshold",
    "DerivationApproach",
    "FeasibilityCheck",
    "LatencyThreshold",
    "MultiRunSummary",
    "RegressionVerdict",
    "RunOutcome",
    "SampleSizeFirstThreshold",
    "ThresholdFirstConfidence",
    "Verdict",
    "WilsonInterval",
    "achieved_power",
    "bound_existence_minimum",
    "check_feasibility",
    "derive_latency_threshold",
    "latency_max",
    "latency_mean",
    "latency_percentile",
    "derive_confidence_first",
    "derive_sample_size_first",
    "derive_threshold_first",
    "evaluate_compliance",
    "evaluate_regression",
    "required_sample_size",
    "summarize_runs",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_lower_bound_from_rate",
]
