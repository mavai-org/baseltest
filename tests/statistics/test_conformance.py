"""Conformance tests validating baseltest against the mavai-R reference
oracle's published fixtures (see `fixtures/NOTE.md` for the pin).

Every oracle assertion is routed through :func:`assert_oracle`, which
records the ``(suite, case, field)`` triple it asserts; the final coverage
test diffs the recorded set against the manifest's binding obligations
(family-mandatory tier plus the committed ``SCOPE.json``). Loading a suite
without asserting its binding fields is therefore a failure, not a silence.

The decision suites are evaluated through the production path wherever one
exists: configuration errors through the engine's preflight
(:func:`refused_parts`), pass-rate verdicts through :func:`execute` with a
scripted service delivering the case's observed successes, and explicit
latency requirements through the engine's latency evaluation. Each suite's
declared methodology version and decision rules are checked against the
ones this package implements, read from the manifest — never a literal.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from baseltest.contract import (
    BaselineCount,
    Criterion,
    LatencyBar,
    LatencyBaseline,
    LatencyBound,
    ServiceContract,
    contains,
)
from baseltest.engine import (
    ConfigurationRefusedError,
    Intent,
    RunPlan,
    RunResult,
    evaluate_latency,
    execute,
    refused_parts,
)
from baseltest.engine.latency import _PERCENTILES
from baseltest.statistics import (
    METHODOLOGY_VERSION,
    ComplianceVerdict,
    ConfigurationError,
    DecisionRule,
    Dimension,
    RegressionVerdict,
    SizingRefusal,
    ThresholdSource,
    Verdict,
    check_feasibility,
    check_sizing_domain,
    compose_overall_verdict,
    decide_nondegeneracy,
    derive_precedence_threshold,
    derive_regression_cutoff,
    design_detectable_rate,
    design_power,
    design_power_at,
    design_required_samples,
    fisher_cutoff,
    implied_alpha,
    latency_max,
    latency_mean,
    latency_percentile,
    minimum_detectable_degradation,
    ordered_configuration_errors,
    plan_nondegeneracy,
    plan_precedence,
    precedence_rank,
    resolved_power,
    resolved_sizing,
    size_compliance,
    wilson_interval,
    wilson_lower_bound,
)
from conformance import ConformanceLedger

FIXTURES_DIR = Path(__file__).parent / "fixtures"

LEDGER = ConformanceLedger()

_INTENTS = {"VERIFICATION": Intent.VERIFICATION, "SMOKE": Intent.SMOKE}
_PERCENT_LABELS = {0.50: "p50", 0.90: "p90", 0.95: "p95", 0.99: "p99"}


def _load(filename: str) -> tuple[float, list[dict[str, Any]]]:
    data = json.loads((FIXTURES_DIR / filename).read_text())
    return data["tolerance"], data["cases"]


def _as_list(value: Any) -> list[Any]:
    # The oracle's serialiser unboxes single-element vectors to scalars.
    return value if isinstance(value, list) else [value]


def assert_oracle(
    suite: str,
    case: dict[str, Any],
    field: str,
    actual: Any,
    abs_tol: float | None = None,
) -> None:
    """Assert one expected field against the oracle and record it.

    Exact equality for booleans, strings, lists, nulls, and whenever no
    tolerance is given (integer-valued fields); float comparison within
    ``abs_tol`` otherwise. Recording happens before the assertion: an
    attempted-and-failed assertion is a failure, not a coverage gap.
    """
    __tracebackhide__ = True
    LEDGER.record(suite, case["name"], field)
    expected = case["expected"][field]
    label = f"{suite}/{case['name']}/{field}"
    if expected is None or isinstance(expected, bool | str | list | dict) or not abs_tol:
        assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"
    else:
        assert actual is not None, f"{label}: expected {expected!r}, but nothing was produced"
        assert actual == pytest.approx(expected, abs=abs_tol), (
            f"{label}: expected {expected!r} within {abs_tol}, got {actual!r}"
        )


def _confidence(alpha: float) -> float:
    """The confidence a contract declares for a case's alpha, as its decimal."""
    return float(Decimal(1) - Decimal(repr(alpha)))


def _scripted_service(successes: int) -> Callable[[str], str]:
    """A service delivering exactly `successes` passing responses first."""
    counter = count(1)

    def invoke(_input: str) -> str:
        return "ok" if next(counter) <= successes else "bad"

    return invoke


def _contract(
    criteria: tuple[Criterion, ...],
    successes: int = 0,
    latency: LatencyBar | None = None,
) -> ServiceContract[str]:
    return ServiceContract(
        contract_id="conformance-scenario",
        invoke=_scripted_service(successes),
        criteria=criteria,
        latency=latency,
    )


def _criterion(name: str = "oracle-scenario", **bar: Any) -> Criterion:
    return Criterion(name=name, postconditions=(contains("ok"),), **bar)


def _regression(inputs: dict[str, Any], alpha_key: str = "alpha", name: str = "c") -> Criterion:
    return _criterion(
        name,
        baseline=BaselineCount(inputs["baseline_successes"], inputs["baseline_trials"]),
        confidence=_confidence(inputs[alpha_key]),
    )


def _compliance(inputs: dict[str, Any], alpha_key: str = "alpha", name: str = "c") -> Criterion:
    return _criterion(
        name, threshold=inputs["threshold"], confidence=_confidence(inputs[alpha_key])
    )


def _configuration_errors(contract: ServiceContract[str], plan: RunPlan) -> list[str]:
    """The ordered configuration-error list the engine's preflight reports."""
    codes = ordered_configuration_errors(part.code for part in refused_parts(contract, plan))
    return [str(code) for code in codes]


def _run(contract: ServiceContract[str], trials: int, intent: Intent) -> RunResult:
    return execute(contract, RunPlan(samples=trials, inputs=("input",), intent=intent))


def _regression_decision(result: RunResult) -> RegressionVerdict:
    decision = result.criterion_results[0].decision
    assert isinstance(decision, RegressionVerdict)
    return decision


def _compliance_decision(result: RunResult) -> ComplianceVerdict:
    decision = result.criterion_results[0].decision
    assert isinstance(decision, ComplianceVerdict)
    return decision


# ---------------------------------------------------------------------------
# Methodology version, decision rules and configuration errors.
# ---------------------------------------------------------------------------


def test_manifest_names_the_methodology_this_package_implements() -> None:
    assert LEDGER.methodology_version == METHODOLOGY_VERSION
    assert {(rule["id"], rule["version"]) for rule in LEDGER.manifest["decisionRules"]} == {
        (rule.value, rule.version) for rule in DecisionRule
    }
    assert LEDGER.configuration_errors == tuple(str(code) for code in ConfigurationError)


@pytest.mark.parametrize("suite", LEDGER.in_scope_suites)
def test_suite_declares_this_methodology_and_known_rules(suite: str) -> None:
    data = json.loads((FIXTURES_DIR / LEDGER.manifest["suites"][suite]["file"]).read_text())
    assert data["methodologyVersion"] == LEDGER.methodology_version
    known = {rule.value for rule in DecisionRule}
    assert {rule["id"] for rule in data["decisionRules"]} <= known
    for case in data["cases"]:
        for rule in _as_list(case.get("decisionRule", [])):
            assert rule in known, f"{suite}/{case['name']}: unknown rule {rule}"


# ---------------------------------------------------------------------------
# Descriptive primitives.
# ---------------------------------------------------------------------------

_WILSON_CI_TOLERANCE, _WILSON_CI_CASES = _load("wilson_ci.json")


@pytest.mark.parametrize("case", _WILSON_CI_CASES, ids=lambda c: c["name"])
def test_wilson_two_sided_interval_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    result = wilson_interval(inputs["successes"], inputs["trials"], inputs["confidence"])
    assert_oracle("wilson_ci", case, "point", result.point_estimate, _WILSON_CI_TOLERANCE)
    assert_oracle("wilson_ci", case, "lower", result.lower_bound, _WILSON_CI_TOLERANCE)
    assert_oracle("wilson_ci", case, "upper", result.upper_bound, _WILSON_CI_TOLERANCE)


_WILSON_LOWER_TOLERANCE, _WILSON_LOWER_CASES = _load("wilson_lower.json")


@pytest.mark.parametrize("case", _WILSON_LOWER_CASES, ids=lambda c: c["name"])
def test_wilson_lower_bound_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    result = wilson_lower_bound(inputs["successes"], inputs["trials"], inputs["confidence"])
    assert_oracle("wilson_lower", case, "lower_bound", result, _WILSON_LOWER_TOLERANCE)


# ---------------------------------------------------------------------------
# regression/fisher.
# ---------------------------------------------------------------------------

_DERIVATION_TOLERANCE, _DERIVATION_CASES = _load("threshold_derivation.json")


@pytest.mark.parametrize(
    "case",
    [c for c in _DERIVATION_CASES if c["approach"] == "sample_size_first"],
    ids=lambda c: c["name"],
)
def test_regression_cutoff_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    contract = _contract((_regression(inputs),))
    plan = RunPlan(samples=inputs["test_samples"], inputs=("i",))
    errors = _configuration_errors(contract, plan)
    assert_oracle("threshold_derivation", case, "configuration_error", errors)
    if errors:
        assert_oracle("threshold_derivation", case, "cutoff_integer", None)
        return
    derived = derive_regression_cutoff(
        inputs["baseline_successes"],
        inputs["baseline_trials"],
        inputs["test_samples"],
        inputs["alpha"],
    )
    tolerance = _DERIVATION_TOLERANCE
    assert_oracle("threshold_derivation", case, "cutoff_integer", derived.cutoff)
    assert_oracle("threshold_derivation", case, "threshold_real", derived.threshold_real, tolerance)
    assert_oracle("threshold_derivation", case, "displayed_rate", derived.displayed_rate, tolerance)
    assert_oracle(
        "threshold_derivation",
        case,
        "size_at_assumed_common_rate",
        derived.size_at_assumed_common_rate,
        tolerance,
    )


@pytest.mark.parametrize(
    "case",
    [c for c in _DERIVATION_CASES if c["approach"] == "threshold_first"],
    ids=lambda c: c["name"],
)
def test_implied_alpha_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    implied = implied_alpha(
        inputs["baseline_successes"],
        inputs["baseline_trials"],
        inputs["test_samples"],
        inputs["declared_cutoff"],
    )
    tolerance = _DERIVATION_TOLERANCE
    assert_oracle("threshold_derivation", case, "implied_alpha", implied.alpha, tolerance)
    assert_oracle("threshold_derivation", case, "is_sound", implied.is_sound)


_REGRESSION_TOLERANCE, _REGRESSION_CASES = _load("regression_decision.json")


@pytest.mark.parametrize("case", _REGRESSION_CASES, ids=lambda c: c["name"])
def test_regression_decision_through_production_verdict_path(case: dict[str, Any]) -> None:
    """PASS iff the observed count meets the Fisher cutoff, as the engine
    judges a criterion carrying its baseline evidence."""
    inputs = case["inputs"]
    trials = inputs["test_samples"]
    contract = _contract((_regression(inputs),), inputs["observed_successes"])
    errors = _configuration_errors(contract, RunPlan(samples=trials, inputs=("i",)))
    assert_oracle("regression_decision", case, "configuration_error", errors)
    if errors:
        with pytest.raises(ConfigurationRefusedError):
            _run(contract, trials, Intent.VERIFICATION)
        assert_oracle("regression_decision", case, "cutoff_integer", None)
        assert_oracle("regression_decision", case, "verdict", None)
        return
    decision = _regression_decision(_run(contract, trials, Intent.VERIFICATION))
    derivation = decision.derivation
    tolerance = _REGRESSION_TOLERANCE
    assert_oracle("regression_decision", case, "cutoff_integer", derivation.cutoff)
    assert_oracle("regression_decision", case, "verdict", decision.verdict.name)
    assert_oracle(
        "regression_decision", case, "threshold_real", derivation.threshold_real, tolerance
    )
    assert_oracle(
        "regression_decision", case, "displayed_rate", derivation.displayed_rate, tolerance
    )
    assert_oracle(
        "regression_decision",
        case,
        "size_at_assumed_common_rate",
        derivation.size_at_assumed_common_rate,
        tolerance,
    )


# ---------------------------------------------------------------------------
# compliance/exact-binomial.
# ---------------------------------------------------------------------------

_COMPLIANCE_TOLERANCE, _COMPLIANCE_CASES = _load("compliance_decision.json")


@pytest.mark.parametrize("case", _COMPLIANCE_CASES, ids=lambda c: c["name"])
def test_compliance_decision_through_production_verdict_path(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    trials = inputs["test_samples"]
    intent = _INTENTS[inputs["intent"]]
    contract = _contract((_compliance(inputs),), inputs["observed_successes"])
    plan = RunPlan(samples=trials, inputs=("i",), intent=intent)
    errors = _configuration_errors(contract, plan)
    assert_oracle("compliance_decision", case, "configuration_error", errors)
    if errors:
        with pytest.raises(ConfigurationRefusedError):
            _run(contract, trials, intent)
        for field in ("k_min", "pass_possible", "verdict"):
            assert_oracle("compliance_decision", case, field, None)
        return
    decision = _compliance_decision(_run(contract, trials, intent))
    tolerance = _COMPLIANCE_TOLERANCE
    assert_oracle("compliance_decision", case, "k_min", decision.minimum_passing)
    assert_oracle("compliance_decision", case, "pass_possible", decision.pass_possible)
    assert_oracle("compliance_decision", case, "verdict", decision.verdict.name)
    assert_oracle(
        "compliance_decision", case, "false_compliance", decision.false_compliance, tolerance
    )
    assert_oracle(
        "compliance_decision",
        case,
        "clopper_pearson_lower",
        decision.clopper_pearson_lower,
        tolerance,
    )


_FEASIBILITY_TOLERANCE, _FEASIBILITY_CASES = _load("feasibility.json")


@pytest.mark.parametrize("case", _FEASIBILITY_CASES, ids=lambda c: c["name"])
def test_feasibility_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    result = check_feasibility(inputs["target_proportion"], inputs["sample_size"], inputs["alpha"])
    assert _FEASIBILITY_TOLERANCE == 0
    assert_oracle("feasibility", case, "feasible", result.feasible)
    assert_oracle("feasibility", case, "minimum_samples", result.minimum_samples)
    assert_oracle("feasibility", case, "criterion", result.criterion)


# ---------------------------------------------------------------------------
# Power and sizing.
# ---------------------------------------------------------------------------

_POWER_TOLERANCE, _POWER_CASES = _load("power_analysis.json")


@pytest.mark.parametrize("case", _POWER_CASES, ids=lambda c: c["name"])
def test_power_analysis_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    approach = case["approach"]
    tolerance = _POWER_TOLERANCE
    if approach == "compliance_sizing":
        sizing = size_compliance(
            inputs["threshold"],
            inputs["min_detectable_effect"],
            inputs["alpha"],
            inputs["power"],
            declared_rate=inputs.get("alternative_rate"),
        )
        assert_oracle("power_analysis", case, "required_samples", sizing.required_samples)
        assert_oracle("power_analysis", case, "achieved_power", sizing.achieved_power, tolerance)
        assert_oracle(
            "power_analysis", case, "alternative_rate", sizing.alternative.rate, tolerance
        )
        assert_oracle("power_analysis", case, "alternative_kind", str(sizing.alternative.kind))
        assert_oracle("power_analysis", case, "first_crossing", sizing.first_crossing)
    elif approach == "regression_power":
        power = design_power(
            inputs["baseline_trials"],
            inputs["test_samples"],
            inputs["alpha"],
            inputs["baseline_rate"],
            inputs["baseline_rate"] - inputs["min_detectable_effect"],
        )
        assert_oracle("power_analysis", case, "design_power", power, tolerance)
    elif approach == "regression_resolved_power":
        counts = (inputs["baseline_successes"], inputs["baseline_trials"], inputs["test_samples"])
        cutoff = fisher_cutoff(*counts, inputs["alpha"])
        power = resolved_power(*counts, inputs["alpha"], inputs["design_alternative_rate"])
        assert_oracle("power_analysis", case, "cutoff_integer", cutoff)
        assert_oracle("power_analysis", case, "resolved_test_power", power, tolerance)
    else:
        assert approach == "regression_mdd"
        mdd = minimum_detectable_degradation(
            inputs["baseline_trials"],
            inputs["test_samples"],
            inputs["alpha"],
            inputs["baseline_rate"],
            inputs["power"],
        )
        assert_oracle("power_analysis", case, "minimum_detectable_degradation", mdd, tolerance)


_SIZING_TOLERANCE, _SIZING_CASES = _load("risk_driven_sizing.json")


def _sizing_refusal(inputs: dict[str, Any]) -> SizingRefusal | None:
    if "baseline_rate" in inputs:
        rate = inputs["baseline_rate"]
    else:
        rate = inputs["baseline_successes"] / inputs["baseline_trials"]
    return check_sizing_domain(
        rate,
        inputs["baseline_trials"],
        inputs.get("design_alternative_rate"),
        inputs.get("test_samples"),
    )


def _assert_refused(case: dict[str, Any], refusal: SizingRefusal) -> None:
    """A refused design: its category, and no number for any numeric field."""
    assert_oracle("risk_driven_sizing", case, "sizing_gate", "REFUSE")
    assert_oracle("risk_driven_sizing", case, "refusal_category", str(refusal))
    for field in case["expected"]:
        if field not in ("sizing_gate", "refusal_category"):
            assert_oracle("risk_driven_sizing", case, field, None)


@pytest.mark.parametrize("case", _SIZING_CASES, ids=lambda c: c["name"])
def test_risk_driven_sizing_matches_oracle(case: dict[str, Any]) -> None:
    inputs = case["inputs"]
    approach = case["approach"]
    tolerance = _SIZING_TOLERANCE
    refusal = _sizing_refusal(inputs)
    if refusal is not None:
        _assert_refused(case, refusal)
        return
    if approach == "required_n":
        design = design_required_samples(
            inputs["baseline_rate"],
            inputs["baseline_trials"],
            inputs["design_alternative_rate"],
            inputs["alpha"],
            inputs["target_power"],
        )
        if design is None:
            _assert_refused(case, SizingRefusal.BASELINE_TOO_SMALL)
            return
        assert_oracle("risk_driven_sizing", case, "required_n", design.required_samples)
        assert_oracle("risk_driven_sizing", case, "achieved_power", design.power, tolerance)
    elif approach == "power_at":
        power = design_power_at(
            inputs["test_samples"],
            inputs["baseline_rate"],
            inputs["baseline_trials"],
            inputs["design_alternative_rate"],
            inputs["alpha"],
        )
        assert_oracle("risk_driven_sizing", case, "power", power, tolerance)
    elif approach == "detectable_rate":
        rate = design_detectable_rate(
            inputs["test_samples"],
            inputs["baseline_rate"],
            inputs["baseline_trials"],
            inputs["alpha"],
            inputs["target_power"],
        )
        assert_oracle("risk_driven_sizing", case, "detectable_rate", rate, tolerance)
    elif approach == "resolved_required_n":
        resolved = resolved_sizing(
            inputs["baseline_successes"],
            inputs["baseline_trials"],
            inputs["design_alternative_rate"],
            inputs["alpha"],
            inputs["target_power"],
        )
        if resolved is None:
            _assert_refused(case, SizingRefusal.BASELINE_TOO_SMALL)
            return
        assert_oracle("risk_driven_sizing", case, "required_n", resolved.required_samples)
        assert_oracle("risk_driven_sizing", case, "resolved_power", resolved.power, tolerance)
        assert_oracle("risk_driven_sizing", case, "first_crossing", resolved.first_crossing)
    else:
        assert approach == "resolved_power_at"
        counts = (inputs["baseline_successes"], inputs["baseline_trials"], inputs["test_samples"])
        cutoff = fisher_cutoff(*counts, inputs["alpha"])
        power = resolved_power(*counts, inputs["alpha"], inputs["design_alternative_rate"])
        assert_oracle("risk_driven_sizing", case, "cutoff_integer", cutoff)
        assert_oracle("risk_driven_sizing", case, "resolved_power", power, tolerance)
    assert_oracle("risk_driven_sizing", case, "sizing_gate", "ADMIT")


# ---------------------------------------------------------------------------
# Latency.
# ---------------------------------------------------------------------------

_LATENCY_TOLERANCE, _LATENCY_CASES = _load("latency_percentile.json")


@pytest.mark.parametrize(
    "case", [c for c in _LATENCY_CASES if "value" in c["expected"]], ids=lambda c: c["name"]
)
def test_latency_percentile_matches_oracle(case: dict[str, Any]) -> None:
    latencies = _as_list(case["inputs"]["latencies"])
    result = latency_percentile(latencies, case["inputs"]["percentile"])
    assert_oracle("latency_percentile", case, "value", result, _LATENCY_TOLERANCE)


@pytest.mark.parametrize(
    "case", [c for c in _LATENCY_CASES if "mean" in c["expected"]], ids=lambda c: c["name"]
)
def test_latency_summary_matches_oracle(case: dict[str, Any]) -> None:
    latencies = _as_list(case["inputs"]["latencies"])
    assert_oracle("latency_percentile", case, "mean", latency_mean(latencies), _LATENCY_TOLERANCE)
    assert_oracle("latency_percentile", case, "max", latency_max(latencies), _LATENCY_TOLERANCE)


_MINIMUMS_TOLERANCE, _MINIMUMS_CASES = _load("latency_percentile_minimums.json")


@pytest.mark.parametrize("case", _MINIMUMS_CASES, ids=lambda c: c["name"])
def test_latency_minimums_and_existence_match_oracle(case: dict[str, Any]) -> None:
    """Exact equality throughout (tolerance 0). The emission minimums are read
    from the artefact writers' own gating table, not a copy of it."""
    assert _MINIMUMS_TOLERANCE == 0
    suite = "latency_percentile_minimums"
    inputs = case["inputs"]
    approach = case["approach"]
    if approach == "emission_non_degeneracy":
        minimums = {level: minimum for _, level, minimum in _PERCENTILES}
        assert_oracle(suite, case, "minimum_contributing_samples", minimums[inputs["percentile"]])
    elif approach == "nondegeneracy_planning":
        planned = plan_nondegeneracy(
            inputs["percentile"], inputs["planned_samples"], inputs["baseline_success_rate"]
        )
        assert_oracle(suite, case, "expected_test_samples", planned.expected_test_samples)
        assert_oracle(
            suite, case, "minimum_contributing_samples", planned.minimum_contributing_samples
        )
        assert_oracle(suite, case, "warning", planned.warning)
        assert_oracle(suite, case, "planned_samples_needed", planned.planned_samples_needed)
    elif approach == "nondegeneracy_decision":
        decision = decide_nondegeneracy(
            inputs["percentile"],
            inputs["test_samples"],
            _INTENTS[inputs["intent"]],
            ThresholdSource(inputs["threshold_source"]),
        )
        assert_oracle(suite, case, "applies", decision.applies)
        assert_oracle(suite, case, "degenerate", decision.degenerate)
        assert_oracle(suite, case, "outcome", str(decision.outcome))
    elif approach == "precedence_existence":
        rank = precedence_rank(
            inputs["baseline_trials"], inputs["test_samples"], inputs["percentile"], inputs["alpha"]
        )
        assert_oracle(suite, case, "saturated", rank is None)
        assert_oracle(suite, case, "rank", rank)
    else:
        assert approach == "precedence_planning"
        planning = plan_precedence(
            inputs["baseline_trials"],
            inputs["planned_samples"],
            inputs["baseline_success_rate"],
            inputs["percentile"],
            inputs["alpha"],
        )
        assert_oracle(suite, case, "expected_test_samples", planning.expected_test_samples)
        assert_oracle(suite, case, "warning", planning.warning)
        assert_oracle(suite, case, "planning_rank", planning.planning_rank)
        assert_oracle(suite, case, "minimum_baseline_trials", planning.minimum_baseline_trials)


_THRESHOLD_TOLERANCE, _THRESHOLD_CASES = _load("latency_threshold.json")


@pytest.mark.parametrize("case", _THRESHOLD_CASES, ids=lambda c: c["name"])
def test_latency_threshold_matches_oracle(case: dict[str, Any]) -> None:
    """The design rule is judged by the engine's preflight on the two
    samplings; the precedence rank on the successful latencies."""
    inputs = case["inputs"]
    baseline = sorted(_as_list(inputs["baseline_latencies"]))
    bar = LatencyBar(
        bounds=(LatencyBound(_PERCENT_LABELS[inputs["p"]]),),
        origin=ThresholdSource.BASELINE_DERIVED,
        confidence=_confidence(inputs["alpha"]),
        baseline=LatencyBaseline(tuple(baseline), inputs["baseline_samples"]),
    )
    contract = _contract((_criterion(),), latency=bar)
    plan = RunPlan(samples=inputs["planned_samples"], inputs=("i",))
    errors = _configuration_errors(contract, plan)
    assert_oracle("latency_threshold", case, "configuration_error", errors)
    if errors:
        for field in ("rank", "threshold", "saturated"):
            assert_oracle("latency_threshold", case, field, None)
        return
    result = derive_precedence_threshold(
        baseline, inputs["test_samples"], inputs["p"], inputs["alpha"]
    )
    tolerance = _THRESHOLD_TOLERANCE
    assert_oracle("latency_threshold", case, "rank", result.rank)
    assert_oracle("latency_threshold", case, "threshold", result.threshold, tolerance)
    assert_oracle("latency_threshold", case, "saturated", result.saturated)
    assert_oracle(
        "latency_threshold", case, "breach_probability", result.breach_probability, tolerance
    )
    assert_oracle("latency_threshold", case, "test_rank", result.test_rank)
    assert_oracle("latency_threshold", case, "n", result.n)
    assert_oracle(
        "latency_threshold", case, "baseline_percentile", result.baseline_percentile, tolerance
    )


_LATENCY_COMPLIANCE_TOLERANCE, _LATENCY_COMPLIANCE_CASES = _load("latency_compliance_decision.json")


def _explicit_bar(percentile: float, threshold_ms: int, alpha: float) -> LatencyBar:
    return LatencyBar(
        bounds=(LatencyBound(_PERCENT_LABELS[percentile], threshold_ms),),
        origin=ThresholdSource.EXPLICIT,
        confidence=_confidence(alpha),
    )


@pytest.mark.parametrize("case", _LATENCY_COMPLIANCE_CASES, ids=lambda c: c["name"])
def test_latency_compliance_decision_through_production_path(case: dict[str, Any]) -> None:
    """Refusal by the engine's preflight on the planned samples; the verdict
    by the engine's latency evaluation on the successful latencies."""
    suite = "latency_compliance_decision"
    inputs = case["inputs"]
    intent = _INTENTS[inputs["intent"]]
    bar = _explicit_bar(inputs["percentile"], inputs["threshold_ms"], inputs["alpha"])
    contract = _contract((_criterion(),), latency=bar)
    plan = RunPlan(samples=inputs["planned_samples"], inputs=("i",), intent=intent)
    errors = _configuration_errors(contract, plan)
    assert_oracle(suite, case, "configuration_error", errors)
    if errors:
        for field in ("test_samples", "within_threshold", "y_min", "pass_possible", "verdict"):
            assert_oracle(suite, case, field, None)
        return
    latencies = _as_list(inputs["latencies"])
    evaluation = evaluate_latency(bar, latencies, inputs["planned_samples"], intent).evaluations[0]
    compliance = evaluation.judgement.compliance
    assert compliance is not None
    assert evaluation.judgement.rule is DecisionRule.LATENCY_COMPLIANCE_EXACT_BINOMIAL
    tolerance = _LATENCY_COMPLIANCE_TOLERANCE
    assert_oracle(suite, case, "test_samples", compliance.test_samples)
    assert_oracle(suite, case, "within_threshold", compliance.within_threshold)
    assert_oracle(suite, case, "y_min", compliance.minimum_within)
    assert_oracle(suite, case, "pass_possible", compliance.pass_possible)
    assert_oracle(suite, case, "verdict", evaluation.verdict.name)
    assert_oracle(suite, case, "false_compliance", compliance.false_compliance, tolerance)
    assert_oracle(suite, case, "clopper_pearson_lower", compliance.clopper_pearson_lower, tolerance)
    assert_oracle(
        suite, case, "observed_percentile_ms", compliance.observed_percentile_ms, tolerance
    )
    assert_oracle(suite, case, "raw_percentile_pass", compliance.raw_percentile_pass)


# ---------------------------------------------------------------------------
# Verdicts and their composition.
# ---------------------------------------------------------------------------

_VERDICT_TOLERANCE, _VERDICT_CASES = _load("verdict.json")


def _functional_criterion(inputs: dict[str, Any], name: str = "c") -> Criterion:
    if "baseline_trials" in inputs:
        return _regression(inputs, name=name)
    return _compliance(inputs, name=name)


@pytest.mark.parametrize(
    "case",
    [c for c in _VERDICT_CASES if c.get("approach") != "test_verdict"],
    ids=lambda c: c["name"],
)
def test_verdict_through_production_verdict_path(case: dict[str, Any]) -> None:
    """One criterion, or a requirement and a baseline as two criteria over the
    same postconditions: refused whole when any part is invalid, otherwise
    each decided by its own rule and composed structurally."""
    inputs = case["inputs"]
    two = case.get("approach") == "two_criteria"
    intent = _INTENTS[inputs.get("intent", "VERIFICATION")]
    if two:
        criteria = (
            _compliance(inputs, "compliance_alpha", inputs["compliance_criterion"]),
            _regression(inputs, "regression_alpha", inputs["regression_criterion"]),
        )
    else:
        criteria = (_functional_criterion(inputs),)
    contract = _contract(criteria, inputs["successes"])
    trials = inputs["trials"]
    errors = _configuration_errors(contract, RunPlan(samples=trials, inputs=("i",), intent=intent))
    assert_oracle("verdict", case, "configuration_error", errors)
    assert_oracle(
        "verdict", case, "observed_rate", inputs["successes"] / trials, _VERDICT_TOLERANCE
    )
    if errors:
        with pytest.raises(ConfigurationRefusedError) as refused:
            _run(contract, trials, intent)
        assert [str(code) for code in refused.value.errors] == errors
        assert_oracle("verdict", case, "verdict", None)
        if two:
            assert_oracle("verdict", case, "criteria", [])
            assert_oracle("verdict", case, "triggering_criteria", [])
            assert_oracle("verdict", case, "false_compliance_envelope", None)
            assert_oracle("verdict", case, "false_degradation_signal_envelope", None)
        return
    result = _run(contract, trials, intent)
    assert result.overall is not None
    assert_oracle("verdict", case, "verdict", result.overall.verdict.name)
    rules = [str(r.criterion.rule) for r in result.criterion_results]
    assert rules == _as_list(case["decisionRule"])
    if not two:
        return
    rows = []
    for criterion_result in result.criterion_results:
        decision = criterion_result.decision
        assert decision is not None
        rows.append(
            {
                "criterion_id": criterion_result.name,
                "procedure": (
                    "COMPLIANCE" if isinstance(decision, ComplianceVerdict) else "REGRESSION"
                ),
                "decisionRule": str(decision.rule),
                "alpha": decision.alpha,
                "verdict": decision.verdict.name,
            }
        )
    assert_oracle("verdict", case, "criteria", rows)
    triggering = [trigger.id for trigger in result.overall.triggering]
    assert_oracle("verdict", case, "triggering_criteria", triggering)
    envelopes = result.envelopes
    tolerance = _VERDICT_TOLERANCE
    assert_oracle(
        "verdict", case, "false_compliance_envelope", envelopes.false_compliance, tolerance
    )
    assert_oracle(
        "verdict",
        case,
        "false_degradation_signal_envelope",
        envelopes.false_degradation_signal,
        tolerance,
    )


def _constraint_row(constraint: dict[str, Any]) -> tuple[dict[str, Any], Verdict]:
    """One latency constraint decided by the engine's latency evaluation —
    by its rule, whatever the dimension's mode."""
    source = ThresholdSource(constraint["source"])
    latencies = _as_list(constraint["latencies"])
    percentile = constraint["percentile"]
    if source is ThresholdSource.EXPLICIT:
        bar = _explicit_bar(percentile, constraint["threshold_ms"], constraint["alpha"])
    else:
        baseline = tuple(sorted(_as_list(constraint["baseline_latencies"])))
        bar = LatencyBar(
            bounds=(LatencyBound(_PERCENT_LABELS[percentile]),),
            origin=source,
            confidence=_confidence(constraint["alpha"]),
            baseline=LatencyBaseline(baseline, len(baseline)),
        )
    evaluation = evaluate_latency(bar, latencies, len(latencies), Intent.VERIFICATION)
    judgement = evaluation.evaluations[0].judgement
    row = {
        "constraint_id": constraint["constraint_id"],
        "source": str(judgement.source),
        "decisionRule": str(judgement.rule),
        "verdict": judgement.verdict.name,
    }
    return row, judgement.verdict


@pytest.mark.parametrize(
    "case",
    [c for c in _VERDICT_CASES if c.get("approach") == "test_verdict"],
    ids=lambda c: c["name"],
)
def test_overall_test_verdict_matches_oracle(case: dict[str, Any]) -> None:
    """V_test: the functional criteria (through the engine) and the latency
    constraints composed by the structural rule the engine uses, over the
    dimensions the case's advisory setting leaves enforced."""
    inputs = case["inputs"]
    advisory = frozenset(Dimension(d) for d in inputs["advisory"])
    criteria: list[tuple[str, Verdict]] = []
    if "functional" in inputs:
        functional = inputs["functional"]
        criterion = _functional_criterion(functional, functional["criterion_id"])
        contract = _contract((criterion,), functional["successes"])
        judged = _run(contract, functional["trials"], Intent.VERIFICATION).criterion_results[0]
        assert judged.verdict is not None
        criteria.append((judged.name, judged.verdict))
    rows = []
    constraints: list[tuple[str, Verdict]] = []
    for constraint in inputs["latency_constraints"]:
        row, verdict = _constraint_row(constraint)
        rows.append(row)
        constraints.append((row["constraint_id"], verdict))
    overall = compose_overall_verdict(criteria, constraints, advisory)
    assert_oracle(
        "verdict",
        case,
        "criteria",
        [{"criterion_id": name, "verdict": verdict.name} for name, verdict in criteria],
    )
    assert_oracle("verdict", case, "latency_constraints", rows)
    rate = overall.rate_verdict.name if overall.rate_verdict is not None else None
    latency = overall.latency_verdict.name if overall.latency_verdict is not None else None
    assert_oracle("verdict", case, "rate_verdict", rate)
    assert_oracle("verdict", case, "latency_verdict", latency)
    for field, mode in (
        ("functional_mode", overall.functional_mode),
        ("latency_mode", overall.latency_mode),
    ):
        assert_oracle("verdict", case, field, None if mode is None else str(mode))
    assert_oracle("verdict", case, "test_verdict", overall.verdict.name)
    assert_oracle(
        "verdict",
        case,
        "triggering",
        [{"kind": str(t.kind), "id": t.id} for t in overall.triggering],
    )


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
