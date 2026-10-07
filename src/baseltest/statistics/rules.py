"""The methodology's decision rules, configuration errors, and test intent.

Statistical Companion 1.5.0 names four verdict-producing procedures, each
with a versioned identifier that travels with every verdict it decides:

- ``regression/fisher`` — empirical regression: the one-sided Fisher exact
  test as an integer cutoff on the test's success count (§3.4);
- ``compliance/exact-binomial`` — normative compliance: the exact one-sided
  binomial test as the smallest passing count (§3.6);
- ``latency/precedence`` — latency regression: the smallest baseline rank
  whose no-degradation breach probability is at most alpha (§12.4);
- ``latency/compliance-exact-binomial`` — an explicit latency requirement:
  the exact binomial test on the count of latencies within it (§12.3.4).

Two configurations are refused before any sample runs, and a refusal names
every applicable code in one fixed order (§5.7.1).
"""

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

METHODOLOGY_VERSION = "1.6.0"
"""The Statistical Companion methodology whose rules this package implements."""


class DecisionRule(StrEnum):
    """A versioned decision rule; the value is its identifier."""

    REGRESSION_FISHER = "regression/fisher"
    COMPLIANCE_EXACT_BINOMIAL = "compliance/exact-binomial"
    LATENCY_PRECEDENCE = "latency/precedence"
    LATENCY_COMPLIANCE_EXACT_BINOMIAL = "latency/compliance-exact-binomial"

    @property
    def version(self) -> int:
        """The rule's version; every rule is at version 1 under 1.5.0."""
        return 1


class ConfigurationError(StrEnum):
    """A configuration refused before any sample runs.

    Declared in the fixed order in which a refusal reports them.
    """

    TEST_LARGER_THAN_BASELINE = "TEST_LARGER_THAN_BASELINE"
    """A test planned larger than the baseline run it consumes — mavai's
    design policy (the baseline is at least as large as any test that
    consumes it), judged once on the two samplings, for pass-rate and
    latency criteria alike, whatever the intent."""

    COMPLIANCE_INFEASIBLE = "COMPLIANCE_INFEASIBLE"
    """A normative design (a pass-rate requirement or an explicit latency
    requirement) too small for any outcome to demonstrate compliance, under
    verification intent."""


def ordered_configuration_errors(
    codes: Iterable[ConfigurationError],
) -> tuple[ConfigurationError, ...]:
    """Every applicable code once, in the fixed reporting order."""
    present = set(codes)
    return tuple(code for code in ConfigurationError if code in present)


def check_test_size(baseline_samples: int, planned_samples: int) -> ConfigurationError | None:
    """The design rule ``TEST_LARGER_THAN_BASELINE``, judged on the samplings.

    Compares the test's planned sample size with the sample size of the
    baseline run it consumes; the latency success counts are never
    compared (they are not known before the run and cannot exceed it).
    """
    if planned_samples > baseline_samples:
        return ConfigurationError.TEST_LARGER_THAN_BASELINE
    return None


class Intent(StrEnum):
    """Whether an infeasible design is refused (verification) or run and
    marked as such (smoke), §5.7; independent of a dimension's enforcement."""

    VERIFICATION = "verification"
    SMOKE = "smoke"


def alpha_from_confidence(confidence: float) -> float:
    """The one-sided level ``1 - confidence``, as the decimal it is written as.

    ``1 - 0.95`` in binary floating point is ``0.050000000000000044``; the
    level a developer declared is ``0.05``, and that is the value the
    exact-boundary convention reads.
    """
    return float(Decimal(1) - Decimal(repr(confidence)))
