"""Conformance tests validating baseltest against the mavai-R reference
oracle's published fixtures (see `fixtures/NOTE.md` for the pin).

Every oracle assertion is routed through :func:`assert_oracle`, which
records the ``(suite, case, binding-field)`` triple it asserts; the final
coverage test diffs the recorded set against the manifest's obligations
(family-mandatory tier plus the committed ``SCOPE.json``). Loading a suite
without asserting its binding fields is therefore a failure, not a
silence — the failure mode that let the empirical decision-rule deviation
ship undetected.

The ``regression_decision`` scenario suite is evaluated through the
production verdict path (`engine.execute`), not a reimplementation: the
threshold is derived exactly as the declarative layer derives it, a
scripted service delivers the case's observed successes, and the verdict
asserted is the one the engine rendered.
"""

import json
from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from conformance import ConformanceLedger

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import RunPlan, execute
from baseltest.engine.run import CriterionResult
from baseltest.statistics import (
    achieved_power,
    bound_existence_minimum,
    check_feasibility,
    derive_latency_threshold,
    derive_sample_size_first,
    derive_threshold_first,
    detectable_rate,
    evaluate_compliance,
    latency_max,
    latency_mean,
    latency_percentile,
    power_at,
    required_sample_size,
    required_samples_for_power,
    wilson_interval,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

LEDGER = ConformanceLedger()


def _load(filename: str) -> tuple[float, list[dict[str, Any]]]:
    data = json.loads((FIXTURES_DIR / filename).read_text())
    return data["tolerance"], data["cases"]


def assert_oracle(
    suite: str,
    case: dict[str, Any],
    field: str,
    actual: Any,
    abs_tol: float | None = None,
) -> None:
    """Assert one binding expected field against the oracle and record it.

    Exact equality for booleans, strings, and whenever no tolerance is
    given (integer-valued fields); float comparison within ``abs_tol``
    otherwise. Recording happens before the assertion: an attempted-and-
    failed assertion is a failure, not a coverage gap.
    """
    __tracebackhide__ = True
    LEDGER.record(suite, case["name"], field)
    expected = case["expected"][field]
    label = f"{suite}/{case['name']}/{field}"
    if isinstance(expected, bool | str) or abs_tol is None or abs_tol == 0:
        assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"
    else:
        assert actual is not None, f"{label}: expected {expected!r}, but nothing was produced"
        assert actual == pytest.approx(expected, abs=abs_tol), (
            f"{label}: expected {expected!r} within {abs_tol}, got {actual!r}"
        )


_WILSON_CI_TOLERANCE, _WILSON_CI_CASES = _load("wilson_ci.json")


@pytest.mark.parametrize("case", _WILSON_CI_CASES, ids=lambda c: c["name"])
def test_wilson_two_sided_interval_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = wilson_interval(
        successes=inputs["successes"],
        trials=inputs["trials"],
        confidence_level=inputs["confidence"],
    )

    assert_oracle("wilson_ci", case, "point", result.point_estimate, _WILSON_CI_TOLERANCE)
    assert_oracle("wilson_ci", case, "lower", result.lower_bound, _WILSON_CI_TOLERANCE)
    assert_oracle("wilson_ci", case, "upper", result.upper_bound, _WILSON_CI_TOLERANCE)


_WILSON_LOWER_TOLERANCE, _WILSON_LOWER_CASES = _load("wilson_lower.json")


@pytest.mark.parametrize("case", _WILSON_LOWER_CASES, ids=lambda c: c["name"])
def test_wilson_lower_bound_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = wilson_lower_bound(
        successes=inputs["successes"],
        trials=inputs["trials"],
        confidence_level=inputs["confidence"],
    )

    assert_oracle("wilson_lower", case, "lower_bound", result, _WILSON_LOWER_TOLERANCE)


_THRESHOLD_TOLERANCE, _THRESHOLD_CASES = _load("threshold_derivation.json")
_SAMPLE_SIZE_FIRST_CASES = [c for c in _THRESHOLD_CASES if c["approach"] == "sample_size_first"]
_THRESHOLD_FIRST_CASES = [c for c in _THRESHOLD_CASES if c["approach"] == "threshold_first"]


@pytest.mark.parametrize("case", _SAMPLE_SIZE_FIRST_CASES, ids=lambda c: c["name"])
def test_sample_size_first_threshold_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = derive_sample_size_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        confidence_level=inputs["confidence"],
    )

    assert_oracle(
        "threshold_derivation", case, "threshold", result.min_pass_rate, _THRESHOLD_TOLERANCE
    )
    assert_oracle(
        "threshold_derivation",
        case,
        "wilson_lower_real",
        result.min_pass_rate,
        _THRESHOLD_TOLERANCE,
    )
    # The integer cutoff and achieved size are the binding decision
    # artefacts of the regression procedure; the derivation must produce
    # them alongside the real-valued threshold.
    assert_oracle("threshold_derivation", case, "cutoff_integer", getattr(result, "cutoff", None))
    assert_oracle(
        "threshold_derivation",
        case,
        "achieved_size",
        getattr(result, "achieved_size", None),
        _THRESHOLD_TOLERANCE,
    )


@pytest.mark.parametrize("case", _THRESHOLD_FIRST_CASES, ids=lambda c: c["name"])
def test_threshold_first_confidence_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = derive_threshold_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        min_pass_rate=inputs["threshold"],
    )

    assert_oracle(
        "threshold_derivation",
        case,
        "implied_confidence",
        result.confidence_level,
        _THRESHOLD_TOLERANCE,
    )
    assert_oracle("threshold_derivation", case, "is_sound", result.is_sound)


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
    assert_oracle("power_analysis", case, "required_samples", sample_size)

    power = achieved_power(
        sample_size=expected["required_samples"],
        confidence_level=inputs["confidence"],
        effect_size=inputs["min_detectable_effect"],
        baseline_rate=inputs["baseline_rate"],
    )
    assert_oracle("power_analysis", case, "achieved_power", power, _POWER_TOLERANCE)


_FEASIBILITY_TOLERANCE, _FEASIBILITY_CASES = _load("feasibility.json")


@pytest.mark.parametrize("case", _FEASIBILITY_CASES, ids=lambda c: c["name"])
def test_feasibility_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = check_feasibility(
        sample_size=inputs["sample_size"],
        target_proportion=inputs["target_proportion"],
        confidence_level=inputs["confidence"],
    )

    assert _FEASIBILITY_TOLERANCE == 0  # exact-match fixture; no float slop expected
    assert_oracle("feasibility", case, "feasible", result.feasible)
    assert_oracle("feasibility", case, "minimum_samples", result.minimum_samples)
    assert_oracle("feasibility", case, "criterion", result.criterion)


_VERDICT_TOLERANCE, _VERDICT_CASES = _load("verdict.json")


@pytest.mark.parametrize("case", _VERDICT_CASES, ids=lambda c: c["name"])
def test_compliance_verdict_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    result = evaluate_compliance(
        successes=inputs["successes"],
        trials=inputs["trials"],
        threshold=inputs["threshold"],
        confidence_level=inputs["confidence"],
    )

    assert_oracle("verdict", case, "passed", result.passed)
    assert_oracle("verdict", case, "observed_rate", result.observed_rate, _VERDICT_TOLERANCE)
    assert_oracle("verdict", case, "test_statistic", result.z_statistic, _VERDICT_TOLERANCE)
    assert_oracle("verdict", case, "p_value", result.p_value, _VERDICT_TOLERANCE)
    assert_oracle(
        "verdict",
        case,
        "false_positive_probability",
        result.false_positive_probability,
        _VERDICT_TOLERANCE,
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
    assert_oracle("latency_percentile", case, "value", result, _LATENCY_TOLERANCE)


@pytest.mark.parametrize(
    "case",
    [c for c in _LATENCY_CASES if "mean" in c["expected"]],
    ids=lambda c: c["name"],
)
def test_latency_summary_matches_oracle(case: dict[str, Any]) -> None:
    latencies = _latencies(case)
    assert_oracle("latency_percentile", case, "mean", latency_mean(latencies), _LATENCY_TOLERANCE)
    assert_oracle("latency_percentile", case, "max", latency_max(latencies), _LATENCY_TOLERANCE)


_MINIMUMS_TOLERANCE, _MINIMUMS_CASES = _load("latency_percentile_minimums.json")
_EMISSION_MINIMUM_CASES = [c for c in _MINIMUMS_CASES if c["approach"] == "emission_non_degeneracy"]


def test_emission_minimums_suite_is_exact_and_complete() -> None:
    assert _MINIMUMS_TOLERANCE == 0  # every value is an integer; equality is exact
    assert len(_EMISSION_MINIMUM_CASES) == 4  # one per supported percentile level


@pytest.mark.parametrize("case", _EMISSION_MINIMUM_CASES, ids=lambda c: c["name"])
def test_percentile_emission_minimums_match_oracle(case: dict[str, Any]) -> None:
    """The emission gate the artefact writers use must equal the published
    family standard exactly — the gating table itself, not a copy."""
    from baseltest.engine.latency import _PERCENTILES

    minimums = {level: minimum for _, level, minimum in _PERCENTILES}
    assert_oracle(
        "latency_percentile_minimums",
        case,
        "minimum_contributing_samples",
        minimums[case["inputs"]["percentile"]],
    )


_THRESHOLD_DERIVE_TOLERANCE, _THRESHOLD_DERIVE_CASES = _load("latency_threshold.json")


@pytest.mark.parametrize("case", _THRESHOLD_DERIVE_CASES, ids=lambda c: c["name"])
def test_latency_threshold_matches_oracle(case: dict[str, Any]) -> None:
    """Every conformance field is an integer or an element of the published
    baseline, so the suite carries tolerance 0 and equality is exact."""
    assert _THRESHOLD_DERIVE_TOLERANCE == 0
    inputs = case["inputs"]

    result = derive_latency_threshold(
        baseline_latencies=inputs["baseline_latencies"],
        percentile=inputs["p"],
        confidence=inputs["confidence"],
    )

    assert_oracle("latency_threshold", case, "rank", result.rank)
    assert_oracle("latency_threshold", case, "threshold", result.threshold)
    assert_oracle("latency_threshold", case, "baseline_percentile", result.baseline_percentile)
    assert_oracle("latency_threshold", case, "n", result.n)


_BOOTSTRAP_TOLERANCE, _BOOTSTRAP_CASES = _load("latency_threshold_bootstrap.json")


@pytest.mark.parametrize("case", _BOOTSTRAP_CASES, ids=lambda c: c["name"])
def test_latency_threshold_bootstrap_conformance_fields(case: dict[str, Any]) -> None:
    """The bootstrap suite's binding fields include the unclamped rank and
    the saturation flag; its bootstrap_upper / point_estimate / diff fields
    are manifest-classified informational (no bootstrap method is
    implemented, deliberately) and are not conformance targets."""
    inputs = case["inputs"]

    result = derive_latency_threshold(
        baseline_latencies=inputs["baseline_latencies"],
        percentile=inputs["p"],
        confidence=inputs["confidence"],
    )

    assert_oracle("latency_threshold_bootstrap", case, "rank", result.rank)
    assert_oracle("latency_threshold_bootstrap", case, "threshold", result.threshold)
    assert_oracle(
        "latency_threshold_bootstrap", case, "baseline_percentile", result.baseline_percentile
    )
    assert_oracle("latency_threshold_bootstrap", case, "n", result.n)
    assert_oracle("latency_threshold_bootstrap", case, "k_raw", result.k_raw)
    assert_oracle("latency_threshold_bootstrap", case, "saturated", result.saturated)


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

    assert_oracle(
        "latency_percentile_minimums",
        case,
        "minimum_baseline_samples",
        bound_existence_minimum(p, confidence),
    )
    at_minimum = derive_latency_threshold(list(range(1, minimum + 1)), p, confidence)
    below_minimum = derive_latency_threshold(list(range(1, minimum)), p, confidence)
    assert not at_minimum.saturated
    assert below_minimum.saturated


_SIZING_TOLERANCE, _SIZING_CASES = _load("risk_driven_sizing.json")
_REQUIRED_N_CASES = [c for c in _SIZING_CASES if c["approach"] == "required_n"]
_POWER_AT_CASES = [c for c in _SIZING_CASES if c["approach"] == "power_at"]
_DETECTABLE_RATE_CASES = [c for c in _SIZING_CASES if c["approach"] == "detectable_rate"]


@pytest.mark.parametrize("case", _REQUIRED_N_CASES, ids=lambda c: c["name"])
def test_required_samples_for_power_matches_oracle(case: dict[str, Any]) -> None:
    """The smallest sample size meeting the target power against the moving
    acceptance floor, plus that size's floor and achieved power — the floor
    through the same Wilson function the decision rule uses (one shared z)."""
    inputs = case["inputs"]

    required = required_samples_for_power(
        baseline_rate=inputs["baseline_rate"],
        minimum_acceptable_rate=inputs["minimum_acceptable_rate"],
        confidence_level=inputs["confidence"],
        target_power=inputs["target_power"],
    )
    assert_oracle("risk_driven_sizing", case, "required_n", required)

    floor = wilson_lower_bound_from_rate(
        inputs["baseline_rate"], case["expected"]["required_n"], inputs["confidence"]
    )
    assert_oracle("risk_driven_sizing", case, "floor", floor, _SIZING_TOLERANCE)

    achieved = power_at(
        sample_size=case["expected"]["required_n"],
        baseline_rate=inputs["baseline_rate"],
        minimum_acceptable_rate=inputs["minimum_acceptable_rate"],
        confidence_level=inputs["confidence"],
    )
    assert_oracle("risk_driven_sizing", case, "achieved_power", achieved, _SIZING_TOLERANCE)


@pytest.mark.parametrize("case", _POWER_AT_CASES, ids=lambda c: c["name"])
def test_power_at_candidate_size_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    floor = wilson_lower_bound_from_rate(
        inputs["baseline_rate"], inputs["test_samples"], inputs["confidence"]
    )
    assert_oracle("risk_driven_sizing", case, "floor", floor, _SIZING_TOLERANCE)

    power = power_at(
        sample_size=inputs["test_samples"],
        baseline_rate=inputs["baseline_rate"],
        minimum_acceptable_rate=inputs["minimum_acceptable_rate"],
        confidence_level=inputs["confidence"],
    )
    assert_oracle("risk_driven_sizing", case, "power", power, _SIZING_TOLERANCE)


@pytest.mark.parametrize("case", _DETECTABLE_RATE_CASES, ids=lambda c: c["name"])
def test_detectable_rate_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]

    rate = detectable_rate(
        sample_size=inputs["test_samples"],
        baseline_rate=inputs["baseline_rate"],
        confidence_level=inputs["confidence"],
        target_power=inputs["target_power"],
    )
    assert_oracle("risk_driven_sizing", case, "detectable_rate", rate, _SIZING_TOLERANCE)


# ---------------------------------------------------------------------------
# The regression_decision scenario suite — the composed decision rules,
# evaluated through the production verdict path.
# ---------------------------------------------------------------------------

_DECISION_TOLERANCE, _DECISION_CASES = _load("regression_decision.json")
_REGRESSION_CASES = [c for c in _DECISION_CASES if c["procedure"] == "REGRESSION"]
_COMPLIANCE_CASES = [c for c in _DECISION_CASES if c["procedure"] == "COMPLIANCE"]


def _scripted_service(successes: int) -> Callable[[str], str]:
    """A service delivering exactly `successes` passing responses first."""
    counter = count(1)

    def invoke(_input: str) -> str:
        return "ok" if next(counter) <= successes else "bad"

    return invoke


def _judged_through_engine(
    threshold: float,
    confidence: float,
    successes: int,
    trials: int,
    cutoff: int | None = None,
) -> CriterionResult:
    """Run one criterion through the production verdict path and return its
    result — the same path a real probabilistic test's verdict takes. A
    regression-procedure criterion carries its derived cutoff, exactly as
    the declarative layer resolves one from a baseline; a compliance
    criterion carries only its declared threshold."""
    criterion = Criterion(
        name="oracle-scenario",
        postconditions=(contains("ok"),),
        threshold=threshold,
        confidence=confidence,
        cutoff=cutoff,
    )
    contract = ServiceContract(
        contract_id="conformance-scenario",
        invoke=_scripted_service(successes),
        criteria=(criterion,),
    )
    result = execute(contract, RunPlan(samples=trials, inputs=("conformance-input",)))
    return result.criterion_results[0]


@pytest.mark.parametrize("case", _REGRESSION_CASES, ids=lambda c: c["name"])
def test_regression_decision_artefacts_from_production_deriver(case: dict[str, Any]) -> None:
    """The derivation the declarative layer performs must produce the
    binding decision artefacts: the real-valued threshold is a report
    obligation, the integer cutoff and achieved size are the decision."""
    inputs = case["inputs"]

    derived = derive_sample_size_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        confidence_level=inputs["confidence"],
    )

    assert_oracle(
        "regression_decision", case, "threshold_real", derived.min_pass_rate, _DECISION_TOLERANCE
    )
    assert_oracle("regression_decision", case, "cutoff_integer", getattr(derived, "cutoff", None))
    # The displayed rate is §3.4's c/n report obligation — the cutoff as a
    # rate, not the observed rate.
    assert_oracle(
        "regression_decision",
        case,
        "displayed_rate",
        getattr(derived, "displayed_rate", None),
        _DECISION_TOLERANCE,
    )
    assert_oracle(
        "regression_decision",
        case,
        "achieved_size",
        getattr(derived, "achieved_size", None),
        _DECISION_TOLERANCE,
    )


@pytest.mark.parametrize("case", _REGRESSION_CASES, ids=lambda c: c["name"])
def test_regression_decision_through_production_verdict_path(case: dict[str, Any]) -> None:
    """The mandated regression rule: PASS iff the raw observed success
    count meets the integer cutoff. The engine's verdict on a criterion
    whose threshold was baseline-derived must match the oracle's."""
    inputs = case["inputs"]

    derived = derive_sample_size_first(
        baseline_successes=inputs["baseline_successes"],
        baseline_trials=inputs["baseline_trials"],
        test_samples=inputs["test_samples"],
        confidence_level=inputs["confidence"],
    )
    judged = _judged_through_engine(
        threshold=derived.min_pass_rate,
        confidence=inputs["confidence"],
        successes=inputs["observed_successes"],
        trials=inputs["test_samples"],
        cutoff=derived.cutoff,
    )

    assert judged.verdict is not None
    assert_oracle("regression_decision", case, "verdict", judged.verdict.name)


@pytest.mark.parametrize("case", _COMPLIANCE_CASES, ids=lambda c: c["name"])
def test_compliance_decision_through_production_verdict_path(case: dict[str, Any]) -> None:
    """The compliance rule (threshold given): PASS iff the test sample's
    own Wilson lower bound clears it — unchanged by the regression fix."""
    inputs = case["inputs"]

    judged = _judged_through_engine(
        threshold=inputs["threshold"],
        confidence=inputs["confidence"],
        successes=inputs["observed_successes"],
        trials=inputs["test_samples"],
    )

    assert_oracle(
        "regression_decision", case, "wilson_lower", judged.lower_bound, _DECISION_TOLERANCE
    )
    assert judged.verdict is not None
    assert_oracle("regression_decision", case, "verdict", judged.verdict.name)


# ---------------------------------------------------------------------------
# The coverage obligation — must stay the last tests in this module, after
# every recording test has run.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suite", LEDGER.in_scope_suites)
def test_vendored_fixture_matches_manifest_hash(suite: str) -> None:
    """The vendored snapshot must be byte-identical to the file the
    manifest describes — silent vendoring drift is a conformance failure."""
    assert LEDGER.vendored_md5(suite) == LEDGER.manifest_md5(suite), (
        f"{suite}: vendored fixture differs from the manifest's content hash; "
        "re-vendor from the pinned mavai-R release"
    )


def test_conformance_coverage_meets_manifest() -> None:
    """Diff the asserted (suite, case, binding-field) triples against the
    manifest's obligation, print the standing, and emit the CI report."""
    LEDGER.write_report()
    print(LEDGER.standing())
    gaps = sorted(LEDGER.gaps())
    assert not gaps, (
        f"{len(gaps)} binding assertions required by the manifest were never made: "
        + ", ".join(f"{s}/{c}/{f}" for s, c, f in gaps[:10])
        + ("…" if len(gaps) > 10 else "")
    )
