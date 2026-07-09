"""Conformance tests validating `baseltest.statistics` against the mavai-R
reference oracle's published fixtures (see `fixtures/NOTE.md` for the pin).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.statistics import (
    achieved_power,
    bound_existence_minimum,
    check_feasibility,
    derive_latency_threshold,
    derive_sample_size_first,
    derive_threshold_first,
    evaluate_compliance,
    latency_max,
    latency_mean,
    latency_percentile,
    required_sample_size,
    wilson_interval,
    wilson_lower_bound,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(filename: str) -> tuple[float, list[dict[str, Any]]]:
    data = json.loads((FIXTURES_DIR / filename).read_text())
    return data["tolerance"], data["cases"]


_WILSON_CI_TOLERANCE, _WILSON_CI_CASES = _load("wilson_ci.json")


@pytest.mark.parametrize("case", _WILSON_CI_CASES, ids=lambda c: c["name"])
def test_wilson_two_sided_interval_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = wilson_interval(
        successes=inputs["successes"],
        trials=inputs["trials"],
        confidence_level=inputs["confidence"],
    )

    assert result.point_estimate == pytest.approx(expected["point"], abs=_WILSON_CI_TOLERANCE)
    assert result.lower_bound == pytest.approx(expected["lower"], abs=_WILSON_CI_TOLERANCE)
    assert result.upper_bound == pytest.approx(expected["upper"], abs=_WILSON_CI_TOLERANCE)


_WILSON_LOWER_TOLERANCE, _WILSON_LOWER_CASES = _load("wilson_lower.json")


@pytest.mark.parametrize("case", _WILSON_LOWER_CASES, ids=lambda c: c["name"])
def test_wilson_lower_bound_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = wilson_lower_bound(
        successes=inputs["successes"],
        trials=inputs["trials"],
        confidence_level=inputs["confidence"],
    )

    assert result == pytest.approx(expected["lower_bound"], abs=_WILSON_LOWER_TOLERANCE)


_THRESHOLD_TOLERANCE, _THRESHOLD_CASES = _load("threshold_derivation.json")
_SAMPLE_SIZE_FIRST_CASES = [c for c in _THRESHOLD_CASES if c["approach"] == "sample_size_first"]
_THRESHOLD_FIRST_CASES = [c for c in _THRESHOLD_CASES if c["approach"] == "threshold_first"]


@pytest.mark.parametrize("case", _SAMPLE_SIZE_FIRST_CASES, ids=lambda c: c["name"])
def test_sample_size_first_threshold_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = derive_sample_size_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        confidence_level=inputs["confidence"],
    )

    assert result.min_pass_rate == pytest.approx(expected["threshold"], abs=_THRESHOLD_TOLERANCE)


@pytest.mark.parametrize("case", _THRESHOLD_FIRST_CASES, ids=lambda c: c["name"])
def test_threshold_first_confidence_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = derive_threshold_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        min_pass_rate=inputs["threshold"],
    )

    assert result.confidence_level == pytest.approx(
        expected["implied_confidence"], abs=_THRESHOLD_TOLERANCE
    )
    assert result.is_sound == expected["is_sound"]


_POWER_TOLERANCE, _POWER_CASES = _load("power_analysis.json")


@pytest.mark.parametrize("case", _POWER_CASES, ids=lambda c: c["name"])
def test_power_analysis_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    sample_size = required_sample_size(
        confidence_level=inputs["confidence"],
        effect_size=inputs["min_detectable_effect"],
        power=inputs["power"],
        baseline_rate=inputs["baseline_rate"],
    )
    assert sample_size == expected["required_samples"]

    power = achieved_power(
        sample_size=expected["required_samples"],
        confidence_level=inputs["confidence"],
        effect_size=inputs["min_detectable_effect"],
        baseline_rate=inputs["baseline_rate"],
    )
    assert power == pytest.approx(expected["achieved_power"], abs=_POWER_TOLERANCE)


_FEASIBILITY_TOLERANCE, _FEASIBILITY_CASES = _load("feasibility.json")


@pytest.mark.parametrize("case", _FEASIBILITY_CASES, ids=lambda c: c["name"])
def test_feasibility_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = check_feasibility(
        sample_size=inputs["sample_size"],
        target_proportion=inputs["target_proportion"],
        confidence_level=inputs["confidence"],
    )

    assert _FEASIBILITY_TOLERANCE == 0  # exact-match fixture; no float slop expected
    assert result.feasible == expected["feasible"]
    assert result.minimum_samples == expected["minimum_samples"]
    assert result.criterion == expected["criterion"]


_VERDICT_TOLERANCE, _VERDICT_CASES = _load("verdict.json")


@pytest.mark.parametrize("case", _VERDICT_CASES, ids=lambda c: c["name"])
def test_compliance_verdict_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    expected = case["expected"]

    result = evaluate_compliance(
        successes=inputs["successes"],
        trials=inputs["trials"],
        threshold=inputs["threshold"],
        confidence_level=inputs["confidence"],
    )

    assert result.passed == expected["passed"]
    assert result.observed_rate == pytest.approx(expected["observed_rate"], abs=_VERDICT_TOLERANCE)
    assert result.z_statistic == pytest.approx(expected["test_statistic"], abs=_VERDICT_TOLERANCE)
    assert result.p_value == pytest.approx(expected["p_value"], abs=_VERDICT_TOLERANCE)
    assert result.false_positive_probability == pytest.approx(
        expected["false_positive_probability"], abs=_VERDICT_TOLERANCE
    )


_LATENCY_TOLERANCE, _LATENCY_CASES = _load("latency_percentile.json")


def _latencies(case: dict[str, Any]) -> list[float]:
    # The oracle's serialiser unboxes single-element vectors to scalars.
    value = case["inputs"]["latencies"]
    return value if isinstance(value, list) else [value]


@pytest.mark.parametrize(
    "case",
    [c for c in _LATENCY_CASES if "value" in c["expected"]],
    ids=lambda c: c["name"],
)
def test_latency_percentile_matches_oracle(case: dict[str, Any]) -> None:
    result = latency_percentile(
        latencies=_latencies(case),
        percentile=case["inputs"]["percentile"],
    )
    assert result == pytest.approx(case["expected"]["value"], abs=_LATENCY_TOLERANCE)


@pytest.mark.parametrize(
    "case",
    [c for c in _LATENCY_CASES if "mean" in c["expected"]],
    ids=lambda c: c["name"],
)
def test_latency_summary_matches_oracle(case: dict[str, Any]) -> None:
    latencies = _latencies(case)
    assert latency_mean(latencies) == pytest.approx(
        case["expected"]["mean"], abs=_LATENCY_TOLERANCE
    )
    assert latency_max(latencies) == pytest.approx(case["expected"]["max"], abs=_LATENCY_TOLERANCE)


_MINIMUMS_TOLERANCE, _MINIMUMS_CASES = _load("latency_percentile_minimums.json")
_EMISSION_MINIMUM_CASES = [c for c in _MINIMUMS_CASES if c["approach"] == "emission_non_degeneracy"]


def test_emission_minimums_suite_is_exact_and_complete() -> None:
    assert _MINIMUMS_TOLERANCE == 0  # every value is an integer; equality is exact
    assert len(_EMISSION_MINIMUM_CASES) == 4  # one per supported percentile level


@pytest.mark.parametrize("case", _EMISSION_MINIMUM_CASES, ids=lambda c: c["name"])
def test_percentile_emission_minimums_match_oracle(case: dict[str, Any]) -> None:
    """The emission gate the artefact writers use must equal the published
    family standard exactly — the gating table itself, not a copy.

    The suite's bound_existence cases (judgement-time minimums for a
    non-saturated order-statistic bound) become conformance targets with
    the latency-criterion work; they are not asserted here.
    """
    from baseltest.engine.latency import _PERCENTILES

    minimums = {level: minimum for _, level, minimum in _PERCENTILES}
    assert (
        minimums[case["inputs"]["percentile"]] == (case["expected"]["minimum_contributing_samples"])
    )


_THRESHOLD_DERIVE_TOLERANCE, _THRESHOLD_DERIVE_CASES = _load("latency_threshold.json")


@pytest.mark.parametrize("case", _THRESHOLD_DERIVE_CASES, ids=lambda c: c["name"])
def test_latency_threshold_matches_oracle(case: dict[str, Any]) -> None:
    """Every conformance field is an integer or an element of the published
    baseline, so the suite carries tolerance 0 and equality is exact."""
    assert _THRESHOLD_DERIVE_TOLERANCE == 0
    inputs = case["inputs"]
    expected = case["expected"]

    result = derive_latency_threshold(
        baseline_latencies=inputs["baseline_latencies"],
        percentile=inputs["p"],
        confidence=inputs["confidence"],
    )

    assert result.rank == expected["rank"]
    assert result.threshold == expected["threshold"]
    assert result.baseline_percentile == expected["baseline_percentile"]
    assert result.n == expected["n"]


_BOOTSTRAP_TOLERANCE, _BOOTSTRAP_CASES = _load("latency_threshold_bootstrap.json")


@pytest.mark.parametrize("case", _BOOTSTRAP_CASES, ids=lambda c: c["name"])
def test_latency_threshold_bootstrap_conformance_fields(case: dict[str, Any]) -> None:
    """The bootstrap suite's conformance fields include the unclamped rank
    and the saturation flag; its bootstrap_upper / point_estimate / diff
    fields are informational comparison content, not conformance targets
    (no bootstrap method is implemented, deliberately)."""
    inputs = case["inputs"]
    expected = case["expected"]

    result = derive_latency_threshold(
        baseline_latencies=inputs["baseline_latencies"],
        percentile=inputs["p"],
        confidence=inputs["confidence"],
    )

    assert result.rank == expected["rank"]
    assert result.threshold == expected["threshold"]
    assert result.baseline_percentile == expected["baseline_percentile"]
    assert result.n == expected["n"]
    assert result.k_raw == expected["k_raw"]
    assert result.saturated == expected["saturated"]


def test_binomial_bound_is_conservative_against_bootstrap() -> None:
    """Fixture-sanity guard: the exact binomial bound dominates the
    informational bootstrap upper bound on every published case."""
    for case in _BOOTSTRAP_CASES:
        assert case["expected"]["threshold"] >= case["expected"]["bootstrap_upper"]


_BOUND_EXISTENCE_CASES = [c for c in _MINIMUMS_CASES if c["approach"] == "bound_existence"]


@pytest.mark.parametrize("case", _BOUND_EXISTENCE_CASES, ids=lambda c: c["name"])
def test_bound_existence_minimums_match_oracle(case: dict[str, Any]) -> None:
    """The judgement-time existence gate equals the published standard, and
    the deriver's saturation flag flips exactly at the published minimum."""
    p = case["inputs"]["percentile"]
    confidence = case["inputs"]["confidence"]
    minimum = case["expected"]["minimum_baseline_samples"]

    assert bound_existence_minimum(p, confidence) == minimum
    at_minimum = derive_latency_threshold(list(range(1, minimum + 1)), p, confidence)
    below_minimum = derive_latency_threshold(list(range(1, minimum)), p, confidence)
    assert not at_minimum.saturated
    assert below_minimum.saturated
