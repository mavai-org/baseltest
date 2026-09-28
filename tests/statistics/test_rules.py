"""The decision-rule vocabulary, configuration errors and the exact boundary."""

from fractions import Fraction

import pytest

from baseltest.statistics import (
    ConfigurationError,
    DecisionRule,
    alpha_from_confidence,
    check_test_size,
    fisher_cutoff,
    fisher_p_value,
    minimum_passing_count,
    ordered_configuration_errors,
    precedence_rank,
)
from baseltest.statistics._exact import (
    at_most_alpha,
    breach_probability_exact,
    exact_decimal,
    fisher_p_value_exact,
)


def test_rules_are_identified_and_versioned() -> None:
    assert [str(rule) for rule in DecisionRule] == [
        "regression/fisher",
        "compliance/exact-binomial",
        "latency/precedence",
        "latency/compliance-exact-binomial",
    ]
    assert {rule.version for rule in DecisionRule} == {1}


def test_configuration_errors_are_reported_once_in_the_fixed_order() -> None:
    codes = [
        ConfigurationError.COMPLIANCE_INFEASIBLE,
        ConfigurationError.TEST_LARGER_THAN_BASELINE,
        ConfigurationError.COMPLIANCE_INFEASIBLE,
    ]
    assert ordered_configuration_errors(codes) == (
        ConfigurationError.TEST_LARGER_THAN_BASELINE,
        ConfigurationError.COMPLIANCE_INFEASIBLE,
    )


def test_a_test_may_equal_but_not_exceed_its_baseline() -> None:
    assert check_test_size(100, 100) is None
    assert check_test_size(100, 101) is ConfigurationError.TEST_LARGER_THAN_BASELINE


@pytest.mark.parametrize(("confidence", "alpha"), [(0.95, 0.05), (0.99, 0.01), (0.999, 0.001)])
def test_alpha_is_the_decimal_the_confidence_was_written_as(
    confidence: float, alpha: float
) -> None:
    assert alpha_from_confidence(confidence) == alpha


def test_declared_decimals_are_read_exactly() -> None:
    assert exact_decimal(0.05) == Fraction(1, 20)
    assert exact_decimal(0.995) == Fraction(199, 200)


def test_the_exact_value_decides_inside_the_guard_band() -> None:
    assert at_most_alpha(0.05 + 1e-12, 0.05, lambda: Fraction(1, 20))
    assert not at_most_alpha(0.05 - 1e-12, 0.05, lambda: Fraction(1, 20) + Fraction(1, 10**15))
    assert at_most_alpha(0.01, 0.05, lambda: pytest.fail("called outside the band"))


def test_fisher_exact_boundary_fails_the_count_whose_p_value_equals_alpha() -> None:
    # 2 of 4 against 12 of 12: P(X <= 2) is exactly 1/20, which double
    # precision puts on the wrong side of 0.05.
    assert fisher_p_value_exact(2, 12, 12, 4) == Fraction(1, 20)
    assert fisher_p_value(2, 12, 12, 4) == pytest.approx(0.05)
    assert fisher_cutoff(12, 12, 4, 0.05) == 3


def test_binomial_exact_boundary_admits_the_count() -> None:
    assert minimum_passing_count(0.6, 10, 0.0463574016) == 9


def test_precedence_exact_boundary_admits_the_top_rank() -> None:
    # A test of 10 at p95 is read at its maximum: breach(n_b) = 10 / (n_b + 10).
    assert breach_probability_exact(190, 190, 10, 10) == Fraction(1, 20)
    assert precedence_rank(190, 10, 0.95, 0.05) == 190
    assert precedence_rank(189, 10, 0.95, 0.05) is None
