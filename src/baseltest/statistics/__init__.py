"""Pure statistical primitives for probabilistic testing of stochastic services.

This package has no dependency on any other `baseltest` package -- it is a
self-contained library of pure functions and immutable data structures
covering:

- Wilson score confidence intervals (`wilson`)
- Pass-rate threshold derivation, in three directions (`threshold`)
- Power analysis / sample size calculation (`power`)

Every public name here is validated against the mavai-R statistical oracle
(see `tests/statistics/` in this repository) to a stated numerical
tolerance, and nothing in this package has side effects.
"""

from .power import achieved_power, required_sample_size
from .threshold import (
    ConfidenceFirstThreshold,
    DerivationApproach,
    SampleSizeFirstThreshold,
    ThresholdFirstConfidence,
    derive_confidence_first,
    derive_sample_size_first,
    derive_threshold_first,
)
from .wilson import (
    WilsonInterval,
    wilson_interval,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)

__all__ = [
    "ConfidenceFirstThreshold",
    "DerivationApproach",
    "SampleSizeFirstThreshold",
    "ThresholdFirstConfidence",
    "WilsonInterval",
    "achieved_power",
    "derive_confidence_first",
    "derive_sample_size_first",
    "derive_threshold_first",
    "required_sample_size",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_lower_bound_from_rate",
]
