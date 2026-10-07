"""Verdicts under the decision rules, and their structural composition."""

import pytest

from baseltest.statistics import (
    DecisionRule,
    Dimension,
    EnforcementMode,
    TriggerKind,
    Verdict,
    compose_overall_verdict,
    evaluate_compliance,
    evaluate_regression,
    structural_composite,
    type_one_envelopes,
)


def test_compliance_passes_at_the_minimum_passing_count() -> None:
    at = evaluate_compliance(successes=148, trials=150, requirement=0.95, alpha=0.05)
    below = evaluate_compliance(successes=147, trials=150, requirement=0.95, alpha=0.05)
    assert (at.verdict, below.verdict) == (Verdict.PASS, Verdict.FAIL)
    assert at.minimum_passing == 148
    assert at.rule is DecisionRule.COMPLIANCE_EXACT_BINOMIAL


def test_compliance_is_not_demonstrated_by_an_observed_rate_above_the_requirement() -> None:
    result = evaluate_compliance(successes=48, trials=50, requirement=0.90, alpha=0.05)
    assert result.observed_rate > 0.90
    assert result.verdict is Verdict.FAIL


def test_compliance_below_the_feasibility_minimum_cannot_pass() -> None:
    result = evaluate_compliance(successes=50, trials=50, requirement=0.95, alpha=0.05)
    assert not result.pass_possible
    assert result.verdict is Verdict.FAIL
    assert result.false_compliance == 0.0


def test_compliance_rejects_counts_out_of_range() -> None:
    with pytest.raises(ValueError, match="successes"):
        evaluate_compliance(successes=11, trials=10, requirement=0.9, alpha=0.05)


def test_compliance_rejects_a_requirement_outside_the_open_interval() -> None:
    with pytest.raises(ValueError, match="requirement"):
        evaluate_compliance(successes=5, trials=10, requirement=1.0, alpha=0.05)


def test_regression_passes_iff_the_count_meets_the_fisher_cutoff() -> None:
    at = evaluate_regression(91, 100, baseline_successes=951, baseline_trials=1000, alpha=0.05)
    below = evaluate_regression(90, 100, baseline_successes=951, baseline_trials=1000, alpha=0.05)
    assert at.cutoff == 91
    assert (at.verdict, below.verdict) == (Verdict.PASS, Verdict.FAIL)
    assert at.rule is DecisionRule.REGRESSION_FISHER


def test_regression_cutoff_is_monotone_through_a_perfect_baseline() -> None:
    near = evaluate_regression(95, 100, 99, 100, alpha=0.05)
    perfect = evaluate_regression(95, 100, 100, 100, alpha=0.05)
    assert near.cutoff <= perfect.cutoff
    assert (near.verdict, perfect.verdict) == (Verdict.PASS, Verdict.FAIL)


def test_regression_zero_baseline_demands_nothing() -> None:
    result = evaluate_regression(0, 50, baseline_successes=0, baseline_trials=100, alpha=0.05)
    assert result.cutoff == 0
    assert result.verdict is Verdict.PASS
    assert result.derivation.size_at_assumed_common_rate is None


def test_structural_composite() -> None:
    assert structural_composite([Verdict.PASS, Verdict.PASS]) is Verdict.PASS
    assert structural_composite([Verdict.INCONCLUSIVE, Verdict.FAIL]) is Verdict.FAIL
    assert structural_composite([Verdict.PASS, Verdict.INCONCLUSIVE]) is Verdict.INCONCLUSIVE
    with pytest.raises(ValueError):
        structural_composite([])


def test_overall_verdict_names_what_decided_it() -> None:
    overall = compose_overall_verdict(
        [("a", Verdict.PASS), ("b", Verdict.FAIL)], [("latency p95", Verdict.FAIL)]
    )
    assert overall.rate_verdict is Verdict.FAIL
    assert overall.latency_verdict is Verdict.FAIL
    assert overall.verdict is Verdict.FAIL
    assert [(t.kind, t.id) for t in overall.triggering] == [
        (TriggerKind.CRITERION, "b"),
        (TriggerKind.LATENCY, "latency p95"),
    ]


def test_a_fail_in_either_dimension_outweighs_an_inconclusive_in_the_other() -> None:
    overall = compose_overall_verdict([("a", Verdict.INCONCLUSIVE)], [("p99", Verdict.FAIL)])
    assert overall.verdict is Verdict.FAIL
    assert [t.id for t in overall.triggering] == ["p99"]


def test_a_missing_dimension_is_left_out() -> None:
    latency_only = compose_overall_verdict([], [("p95", Verdict.PASS)])
    assert latency_only.rate_verdict is None
    assert latency_only.verdict is Verdict.PASS
    assert latency_only.triggering == ()


def test_every_dimension_is_enforced_by_default() -> None:
    overall = compose_overall_verdict([("a", Verdict.PASS)], [("p95", Verdict.PASS)])
    assert overall.functional_mode is EnforcementMode.ENFORCED
    assert overall.latency_mode is EnforcementMode.ENFORCED
    assert overall.enforced_dimensions == (Dimension.FUNCTIONAL, Dimension.LATENCY)


def test_an_advisory_dimension_is_reported_but_never_decides_the_test() -> None:
    overall = compose_overall_verdict(
        [("a", Verdict.PASS)], [("p95", Verdict.FAIL)], frozenset({Dimension.LATENCY})
    )
    assert overall.latency_verdict is Verdict.FAIL
    assert overall.latency_mode is EnforcementMode.ADVISORY
    assert overall.verdict is Verdict.PASS
    assert overall.triggering == ()


def test_the_triggering_list_names_enforced_items_only() -> None:
    overall = compose_overall_verdict(
        [("a", Verdict.FAIL)], [("p95", Verdict.FAIL)], frozenset({Dimension.FUNCTIONAL})
    )
    assert overall.rate_verdict is Verdict.FAIL
    assert overall.verdict is Verdict.FAIL
    assert [t.id for t in overall.triggering] == ["p95"]


def test_with_no_enforced_dimension_the_test_passes() -> None:
    both = frozenset({Dimension.FUNCTIONAL, Dimension.LATENCY})
    overall = compose_overall_verdict([("a", Verdict.FAIL)], [("p95", Verdict.INCONCLUSIVE)], both)
    assert (overall.rate_verdict, overall.latency_verdict) == (Verdict.FAIL, Verdict.INCONCLUSIVE)
    assert overall.verdict is Verdict.PASS
    assert overall.enforced_dimensions == ()
    advisory_alone = compose_overall_verdict(
        [("a", Verdict.FAIL)], [], frozenset({Dimension.FUNCTIONAL})
    )
    assert advisory_alone.latency_mode is None
    assert advisory_alone.verdict is Verdict.PASS


def test_a_test_with_nothing_to_compose_is_a_defect() -> None:
    with pytest.raises(ValueError):
        compose_overall_verdict([], [])


def test_envelopes_split_by_direction() -> None:
    envelopes = type_one_envelopes(
        [
            (DecisionRule.COMPLIANCE_EXACT_BINOMIAL, 0.01),
            (DecisionRule.REGRESSION_FISHER, 0.05),
            (DecisionRule.LATENCY_COMPLIANCE_EXACT_BINOMIAL, 0.05),
            (DecisionRule.LATENCY_PRECEDENCE, 0.05),
        ]
    )
    assert envelopes.false_compliance == pytest.approx(0.06)
    assert envelopes.false_degradation_signal == pytest.approx(0.10)
    assert type_one_envelopes([]).false_compliance is None
