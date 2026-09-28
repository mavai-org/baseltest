"""Pure statistical primitives for probabilistic testing of stochastic services.

This package has no dependency on any other `baseltest` package -- it is a
self-contained library of pure functions and immutable data structures
implementing the Statistical Companion's methodology 1.5.0:

- the decision rules, configuration errors and test intent (`rules`), and
  the exact-boundary convention every exact rule shares (`_exact`);
- empirical regression under ``regression/fisher`` (`regression`) and its
  design and resolved sizing (`sizing`);
- normative compliance under ``compliance/exact-binomial`` (`compliance`)
  and its feasibility gate (`feasibility`);
- latency percentiles, ``latency/precedence`` and
  ``latency/compliance-exact-binomial`` (`latency`);
- verdicts and their composition into the test's verdict (`verdict`);
- Wilson score intervals, kept as descriptive intervals (`wilson`).

Every public name here is validated against the mavai-R statistical oracle
(see `tests/statistics/` in this repository) to a stated numerical
tolerance, and nothing in this package has side effects.
"""

from ._constants import DEFAULT_CONFIDENCE_LEVEL, DEFAULT_POWER
from .compliance import (
    AlternativeKind,
    ComplianceSizing,
    SizingAlternative,
    clopper_pearson_lower,
    compliance_sizing_alternative,
    minimum_feasible_samples,
    minimum_passing_count,
    pass_probability,
    size_compliance,
)
from .feasibility import FeasibilityCheck, check_feasibility
from .latency import (
    AdvisoryOutcome,
    LatencyCompliance,
    LatencyJudgement,
    LatencyMode,
    NondegeneracyDecision,
    NondegeneracyOutcome,
    NondegeneracyPlanning,
    PrecedencePlanning,
    PrecedenceThreshold,
    ThresholdSource,
    breach_probability,
    decide_nondegeneracy,
    derive_precedence_threshold,
    evaluate_latency_compliance,
    expected_successful_count,
    judge_latency_constraint,
    latency_max,
    latency_mean,
    latency_percentile,
    minimum_contributing_samples,
    nearest_rank,
    plan_nondegeneracy,
    plan_precedence,
    precedence_rank,
)
from .proportion import proportion_standard_error, proportion_variance
from .regression import (
    MDD_POWER,
    ImpliedAlpha,
    RegressionDerivation,
    derive_regression_cutoff,
    design_power,
    fisher_cutoff,
    fisher_p_value,
    implied_alpha,
    minimum_detectable_degradation,
    resolved_detectable_rate,
    resolved_power,
    size_at_assumed_common_rate,
)
from .rules import (
    METHODOLOGY_VERSION,
    ConfigurationError,
    DecisionRule,
    Intent,
    alpha_from_confidence,
    check_test_size,
    ordered_configuration_errors,
)
from .sizing import (
    DesignSizing,
    ResolvedSizing,
    SizingRefusal,
    check_sizing_domain,
    design_detectable_rate,
    design_power_at,
    design_required_samples,
    resolved_sizing,
)
from .verdict import (
    ComplianceVerdict,
    Direction,
    Envelopes,
    OverallVerdict,
    RegressionVerdict,
    Trigger,
    TriggerKind,
    Verdict,
    compose_overall_verdict,
    direction_of,
    evaluate_compliance,
    evaluate_regression,
    structural_composite,
    type_one_envelopes,
)
from .wilson import (
    WilsonInterval,
    wilson_interval,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)

__all__ = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_POWER",
    "MDD_POWER",
    "METHODOLOGY_VERSION",
    "AdvisoryOutcome",
    "AlternativeKind",
    "ComplianceSizing",
    "ComplianceVerdict",
    "ConfigurationError",
    "DecisionRule",
    "DesignSizing",
    "Direction",
    "Envelopes",
    "FeasibilityCheck",
    "ImpliedAlpha",
    "Intent",
    "LatencyCompliance",
    "LatencyJudgement",
    "LatencyMode",
    "NondegeneracyDecision",
    "NondegeneracyOutcome",
    "NondegeneracyPlanning",
    "OverallVerdict",
    "PrecedencePlanning",
    "PrecedenceThreshold",
    "RegressionDerivation",
    "RegressionVerdict",
    "ResolvedSizing",
    "SizingAlternative",
    "SizingRefusal",
    "ThresholdSource",
    "Trigger",
    "TriggerKind",
    "Verdict",
    "WilsonInterval",
    "alpha_from_confidence",
    "breach_probability",
    "check_feasibility",
    "check_sizing_domain",
    "check_test_size",
    "clopper_pearson_lower",
    "compliance_sizing_alternative",
    "compose_overall_verdict",
    "decide_nondegeneracy",
    "derive_precedence_threshold",
    "derive_regression_cutoff",
    "design_detectable_rate",
    "design_power",
    "design_power_at",
    "design_required_samples",
    "direction_of",
    "evaluate_compliance",
    "evaluate_latency_compliance",
    "evaluate_regression",
    "expected_successful_count",
    "fisher_cutoff",
    "fisher_p_value",
    "implied_alpha",
    "judge_latency_constraint",
    "latency_max",
    "latency_mean",
    "latency_percentile",
    "minimum_contributing_samples",
    "minimum_detectable_degradation",
    "minimum_feasible_samples",
    "minimum_passing_count",
    "nearest_rank",
    "ordered_configuration_errors",
    "pass_probability",
    "plan_nondegeneracy",
    "plan_precedence",
    "precedence_rank",
    "proportion_standard_error",
    "proportion_variance",
    "resolved_detectable_rate",
    "resolved_power",
    "resolved_sizing",
    "size_at_assumed_common_rate",
    "size_compliance",
    "structural_composite",
    "type_one_envelopes",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_lower_bound_from_rate",
]
