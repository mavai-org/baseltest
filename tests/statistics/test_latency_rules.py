"""Latency decisions: precedence, explicit compliance, and the planning checks."""

import pytest

from baseltest.statistics import (
    AdvisoryOutcome,
    Intent,
    LatencyMode,
    NondegeneracyOutcome,
    ThresholdSource,
    Verdict,
    derive_precedence_threshold,
    evaluate_latency_compliance,
    judge_latency_constraint,
    nearest_rank,
    plan_nondegeneracy,
    plan_precedence,
)


def test_nearest_rank_is_integer_arithmetic() -> None:
    assert nearest_rank(192, 0.95) == 183
    assert nearest_rank(100, 0.99) == 99
    with pytest.raises(ValueError, match="p50, p90, p95, p99"):
        nearest_rank(10, 0.75)


def test_precedence_threshold_is_an_observed_baseline_latency() -> None:
    baseline = list(range(1, 936))
    derived = derive_precedence_threshold(baseline, 192, 0.95, 0.05)
    assert derived.rank == 911
    assert derived.threshold == 911
    assert not derived.saturated


def test_saturated_precedence_has_no_threshold() -> None:
    derived = derive_precedence_threshold(list(range(100)), 15, 0.95, 0.05)
    assert derived.saturated
    assert derived.rank is None and derived.threshold is None


def test_explicit_requirement_counts_ties_as_within() -> None:
    latencies = [500] * 99 + [900]
    result = evaluate_latency_compliance(latencies, 500, 0.95, 0.05)
    assert result.within_threshold == 99
    assert result.verdict is Verdict.PASS


def test_explicit_requirement_is_inconclusive_when_no_count_can_pass() -> None:
    result = evaluate_latency_compliance([100] * 58, 500, 0.95, 0.05)
    assert not result.pass_possible
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.advisory_percentile_pass is True


def test_raw_percentile_within_does_not_demonstrate_compliance() -> None:
    latencies = [400] * 96 + [900] * 4
    result = evaluate_latency_compliance(latencies, 500, 0.95, 0.05)
    assert result.advisory_percentile_pass is True
    assert result.verdict is Verdict.FAIL


def test_baseline_derived_constraint_below_the_minimum_is_inconclusive_under_verification() -> None:
    judgement = judge_latency_constraint(
        [100] * 15,
        0.95,
        0.05,
        source=ThresholdSource.BASELINE_DERIVED,
        mode=LatencyMode.ENFORCED,
        intent=Intent.VERIFICATION,
        baseline_latencies=list(range(1, 1001)),
    )
    assert judgement.verdict is Verdict.INCONCLUSIVE
    assert judgement.nondegeneracy is not None
    assert judgement.nondegeneracy.outcome is NondegeneracyOutcome.INCONCLUSIVE


def test_baseline_derived_constraint_below_the_minimum_is_indicative_under_smoke() -> None:
    judgement = judge_latency_constraint(
        [100] * 15,
        0.95,
        0.05,
        source=ThresholdSource.BASELINE_DERIVED,
        mode=LatencyMode.ENFORCED,
        intent=Intent.SMOKE,
        baseline_latencies=list(range(1, 1001)),
    )
    assert judgement.indicative
    assert judgement.verdict is Verdict.PASS


def test_advisory_constraint_never_carries_a_verdict() -> None:
    judgement = judge_latency_constraint(
        [900] * 20,
        0.95,
        0.05,
        source=ThresholdSource.EXPLICIT,
        mode=LatencyMode.ADVISORY,
        intent=Intent.VERIFICATION,
        threshold_ms=500,
    )
    assert judgement.verdict is None
    assert judgement.rule is None
    assert judgement.advisory is AdvisoryOutcome.ADVISORY_WARN


def test_planning_warns_on_the_expected_count_and_names_the_figures() -> None:
    nondegeneracy = plan_nondegeneracy(0.99, 110, 0.80)
    assert (nondegeneracy.expected_test_samples, nondegeneracy.warning) == (88, True)
    assert nondegeneracy.planned_samples_needed == 125
    precedence = plan_precedence(400, 200, 0.80, 0.99, 0.05)
    assert precedence.warning and precedence.minimum_baseline_trials == 554


def test_planning_with_no_expected_successes_warns_without_a_figure() -> None:
    planning = plan_precedence(100, 10, 0.01, 0.95, 0.05)
    assert planning.warning
    assert planning.minimum_baseline_trials is None
