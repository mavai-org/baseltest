"""The smoke-intent rules: a requirement FAILs only on evidence of falling short."""

import pytest

from baseltest.statistics import (
    DecisionRule,
    Intent,
    Verdict,
    evaluate_latency_compliance,
    evaluate_smoke_compliance,
    requirement_rule,
    smoke_required_pass,
    type_one_envelopes,
)


@pytest.mark.parametrize(
    ("requirement", "samples", "alpha", "required"),
    [
        (0.99, 100, 0.05, 97),
        (0.99, 30, 0.05, 29),
        (0.99, 20, 0.05, 19),
        (0.99, 5, 0.05, 5),
        (0.9, 5, 0.05, 3),
        (0.5, 1, 0.05, 0),
        (0.995, 477, 0.05, 472),
        (0.95, 150, 0.05, 138),
        (0.95, 50, 0.05, 45),
        (0.95, 58, 0.05, 52),
        (0.5, 5, 1 / 32, 1),
    ],
)
def test_required_pass_matches_the_worked_values(
    requirement: float, samples: int, alpha: float, required: int
) -> None:
    assert smoke_required_pass(requirement, samples, alpha) == required


def test_the_exact_boundary_fails_the_count_whose_lower_tail_equals_alpha() -> None:
    # P(K <= 0 | 5, 0.5) = 1/32 exactly: inclusive, so zero passes FAILs.
    decision = evaluate_smoke_compliance(0, 5, 0.5, 0.03125)
    assert decision.required_pass == 1
    assert decision.verdict is Verdict.FAIL


def test_smoke_passes_at_the_required_count_and_fails_one_below() -> None:
    at = evaluate_smoke_compliance(97, 100, 0.99, 0.05)
    below = evaluate_smoke_compliance(96, 100, 0.99, 0.05)
    assert (at.verdict, below.verdict) == (Verdict.PASS, Verdict.FAIL)
    assert at.rule is DecisionRule.COMPLIANCE_SMOKE_EXACT_BINOMIAL
    assert below.p_value == pytest.approx(0.0183740364446497, abs=1e-12)
    assert at.minimum_passing is None and not at.pass_possible
    assert at.feasibility_minimum == 299


def test_smoke_decides_by_its_own_rule_above_the_feasibility_minimum() -> None:
    # 147 of 150 at 0.95 is not demonstrated (k_min is 148), and is no
    # evidence of falling short either.
    decision = evaluate_smoke_compliance(147, 150, 0.95, 0.05)
    assert decision.verdict is Verdict.PASS
    assert (decision.required_pass, decision.minimum_passing) == (138, 148)
    assert decision.pass_possible


def test_no_count_can_fail_a_low_requirement_over_one_sample() -> None:
    decision = evaluate_smoke_compliance(0, 1, 0.5, 0.05)
    assert decision.verdict is Verdict.PASS
    assert not decision.fail_possible
    assert decision.false_non_compliance == 0.0


def test_the_requirement_rule_is_the_intents() -> None:
    assert requirement_rule(Intent.VERIFICATION) is DecisionRule.COMPLIANCE_EXACT_BINOMIAL
    assert requirement_rule(Intent.SMOKE) is DecisionRule.COMPLIANCE_SMOKE_EXACT_BINOMIAL


def test_smoke_decisions_enter_neither_envelope() -> None:
    envelopes = type_one_envelopes(
        [
            (DecisionRule.COMPLIANCE_SMOKE_EXACT_BINOMIAL, 0.05),
            (DecisionRule.LATENCY_SMOKE_COMPLIANCE_EXACT_BINOMIAL, 0.05),
        ]
    )
    assert envelopes.false_compliance is None
    assert envelopes.false_degradation_signal is None


class TestLatencyTwin:
    def test_p99_over_100_latencies_needs_97_within(self) -> None:
        latencies = [100.0] * 97 + [2_000.0] * 3
        decided = evaluate_latency_compliance(latencies, 1_200, 0.99, 0.05, Intent.SMOKE)
        assert decided.rule is DecisionRule.LATENCY_SMOKE_COMPLIANCE_EXACT_BINOMIAL
        assert decided.required_within == 97
        assert decided.minimum_within is None
        assert decided.verdict is Verdict.PASS
        failing = evaluate_latency_compliance(
            [*latencies[:96], 2_000.0, *latencies[97:]], 1_200, 0.99, 0.05, Intent.SMOKE
        )
        assert failing.verdict is Verdict.FAIL

    def test_no_successful_latency_is_inconclusive(self) -> None:
        decided = evaluate_latency_compliance([], 500, 0.95, 0.05, Intent.SMOKE)
        assert decided.verdict is Verdict.INCONCLUSIVE
        assert decided.required_within is None

    def test_verification_is_unchanged(self) -> None:
        decided = evaluate_latency_compliance([100.0] * 59, 500, 0.95, 0.05)
        assert decided.rule is DecisionRule.LATENCY_COMPLIANCE_EXACT_BINOMIAL
        assert decided.required_within == decided.minimum_within == 59
        assert decided.verdict is Verdict.PASS
