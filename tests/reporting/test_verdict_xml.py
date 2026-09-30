"""The canonical verdict record: family schema shape, mavai namespace."""

import shutil
import subprocess
from itertools import count
from pathlib import Path
from xml.etree import ElementTree

import pytest

import baseltest
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
    METHODOLOGY_VERSION,
    ComplianceVerdict,
    ConfigurationRefusedError,
    Intent,
    RegressionVerdict,
    RunKind,
    RunPlan,
    RunResult,
    execute,
)
from baseltest.reporting import (
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    parse_verdict_record,
    render_refused_record,
    render_verdict_record,
    write_verdict_record,
)
from baseltest.statistics import ThresholdSource

NS = "{http://mavai.org/verdict/1.0}"
XSD = Path(__file__).resolve().parents[1] / "conformance/interchange/verdict-1.7.xsd"

RISK_DRIVEN_DESIGN = RunDesign(
    approach="confidence-first (risk-driven)",
    claims=(
        ClaimDisclosure(
            criterion="keeps-up",
            baseline_rate=0.9,
            design_alternative_rate=0.84,
            confidence=0.95,
            target_power=0.8,
            required_n=214,
        ),
    ),
    governing="keeps-up",
    baseline=BaselineDisclosure(
        source_file="sized-one-abc.yaml",
        generated_at="2026-07-12T10:00:00+00:00",
        samples=1000,
        baseline_rate=0.9,
        derived_threshold=0.85,
    ),
)


def run_result() -> RunResult:
    contract = ServiceContract(
        contract_id="refund-confirmation",
        invoke=lambda v: f"refund {v}",
        criteria=(
            Criterion(name="relevant", postconditions=(contains("refund"),), threshold=0.5),
            Criterion(name="prompt-echo", postconditions=(contains("a"),), threshold=0.5),
        ),
    )
    return execute(
        contract,
        RunPlan(samples=100, inputs=("a", "b"), kind=RunKind.TEST, intent=Intent.VERIFICATION),
    )


def exact_service(successes: int) -> object:
    counter = count(1)
    return lambda _value: "ok" if next(counter) <= successes else "bad"


def regression_result(design_alternative_rate: float | None = None) -> RunResult:
    criterion = Criterion(
        name="extraction",
        postconditions=(contains("ok"),),
        baseline=BaselineCount(951, 1000),
        design_alternative_rate=design_alternative_rate,
    )
    contract = ServiceContract(
        contract_id="offer-extraction",
        invoke=exact_service(93),  # type: ignore[arg-type]
        criteria=(criterion,),
    )
    return execute(contract, RunPlan(samples=100, inputs=("a",), kind=RunKind.TEST))


def assert_valid(tmp_path: Path, text: str) -> None:
    """Validate a record against this package's vendored family XSD — never
    another framework's embedded copy reached across repositories."""
    assert XSD.is_file(), f"vendored family XSD missing: {XSD}"
    xmllint = shutil.which("xmllint")
    if xmllint is None:
        pytest.skip("xmllint not available on this machine")
    record = tmp_path / "record.xml"
    record.write_text(text, encoding="utf-8")
    completed = subprocess.run(
        [xmllint, "--noout", "--schema", str(XSD), str(record)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


class TestVerdictRecord:
    def test_record_shape(self) -> None:
        text = render_verdict_record(run_result())
        root = ElementTree.fromstring(text)
        assert root.tag == f"{NS}verdict-record"
        assert root.get("version") == "1.7"
        assert root.get("methodology-version") == METHODOLOGY_VERSION
        assert root.get("generator") == f"baseltest {baseltest.__version__}"

        identity = root.find(f"{NS}identity")
        assert identity is not None and identity.get("use-case-id") == "refund-confirmation"

        # Every input the run drove is named, not only one a failure came
        # from: a record naming the inputs that misbehaved and leaving the
        # rest anonymous names some rows and not others.
        inputs = root.find(f"{NS}inputs")
        assert inputs is not None
        assert [
            (entry.get("index"), entry.get("excerpt")) for entry in inputs.findall(f"{NS}input")
        ] == [("0", "a"), ("1", "b")]

        execution = root.find(f"{NS}execution")
        assert execution is not None
        assert execution.get("planned-samples") == "100"
        assert execution.get("intent") == "VERIFICATION"
        # per-trial conjunction: 'b' inputs fail prompt-echo -> half succeed overall
        assert execution.get("successes") == "50"
        assert execution.get("failures") == "50"

        per_criterion = root.find(f"{NS}per-criterion")
        assert per_criterion is not None
        rows = per_criterion.findall(f"{NS}criterion")
        assert [r.get("id") for r in rows] == ["relevant", "prompt-echo"]
        assert rows[0].get("verdict") == "PASS"
        assert {r.get("decision-rule") for r in rows} == {"compliance/exact-binomial"}
        assert {r.get("decision-rule-version") for r in rows} == {"1"}
        composite = per_criterion.find(f"{NS}composite")
        assert composite is not None

        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("value") in ("PASS", "FAIL")
        # One rule decided the whole test, so the verdict states it.
        assert verdict.get("decision-rule") == "compliance/exact-binomial"
        assert verdict.get("configuration-error") is None

        covariates = root.find(f"{NS}covariates")
        assert covariates is not None and covariates.get("aligned") == "true"
        termination = root.find(f"{NS}termination")
        assert termination is not None and termination.get("reason") == "COMPLETED"

    def test_single_compliance_criterion_emits_statistics(self) -> None:
        contract = ServiceContract(
            contract_id="solo",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
        )
        result = execute(contract, RunPlan(samples=100, inputs=("a",), kind=RunKind.TEST))
        root = ElementTree.fromstring(render_verdict_record(result))
        statistics = root.find(f"{NS}statistics")
        assert statistics is not None
        assert statistics.get("threshold") == "0.5"
        assert statistics.get("threshold-origin") == "UNSPECIFIED"
        assert float(statistics.get("wilson-lower") or 0) > 0.9
        assert statistics.get("design-power") is None

    def test_a_regression_criterion_states_its_cutoff_and_both_powers(self, tmp_path: Path) -> None:
        text = render_verdict_record(regression_result(0.90))
        root = ElementTree.fromstring(text)
        statistics = root.find(f"{NS}statistics")
        assert statistics is not None
        assert statistics.get("threshold") == "0.91"  # the cutoff 91 of 100
        assert float(statistics.get("size-at-assumed-common-rate") or 0) == pytest.approx(
            0.0339673926, abs=1e-9
        )
        assert statistics.get("design-alternative-rate") == "0.9"
        assert float(statistics.get("design-power") or 0) == pytest.approx(0.55, abs=0.01)
        assert float(statistics.get("resolved-test-power") or 0) == pytest.approx(0.549, abs=0.001)
        row = root.find(f"{NS}per-criterion/{NS}criterion")
        assert row is not None and row.get("decision-rule") == "regression/fisher"
        assert_valid(tmp_path, text)

    def test_without_a_design_alternative_no_power_is_stated(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(regression_result()))
        statistics = root.find(f"{NS}statistics")
        assert statistics is not None
        assert statistics.get("design-power") is None
        assert statistics.get("resolved-test-power") is None

    def test_written_file_is_identity_named(self, tmp_path: Path) -> None:
        result = run_result()
        path = write_verdict_record(result, tmp_path)
        assert path.name == f"refund-confirmation-{result.inputs_identity[:12]}.xml"
        assert path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')

    def test_failure_reasons_become_clauses(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(run_result()))
        failures = root.find(f"{NS}postcondition-failures")
        assert failures is not None
        clauses = failures.findall(f"{NS}clause")
        assert clauses and all(int(c.get("count") or 0) > 0 for c in clauses)

    def test_validates_against_the_family_xsd(self, tmp_path: Path) -> None:
        assert_valid(tmp_path, render_verdict_record(run_result()))


class TestTwoCriteria:
    def test_a_requirement_and_a_baseline_state_their_rules_on_the_rows_only(
        self, tmp_path: Path
    ) -> None:
        compliance = Criterion(name="req", postconditions=(contains("ok"),), threshold=0.8)
        regression = Criterion(
            name="reg", postconditions=(contains("ok"),), baseline=BaselineCount(951, 1000)
        )
        contract = ServiceContract(
            contract_id="two",
            invoke=exact_service(93),  # type: ignore[arg-type]
            criteria=(compliance, regression),
        )
        result = execute(contract, RunPlan(samples=100, inputs=("a",)))
        text = render_verdict_record(result)
        root = ElementTree.fromstring(text)
        rows = root.findall(f"{NS}per-criterion/{NS}criterion")
        assert [r.get("decision-rule") for r in rows] == [
            "compliance/exact-binomial",
            "regression/fisher",
        ]
        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("decision-rule") is None
        assert_valid(tmp_path, text)


def two_criteria_result(successes: int) -> RunResult:
    """A requirement and a baseline over the same postcondition, 100 samples."""
    compliance = Criterion(name="req", postconditions=(contains("ok"),), threshold=0.8)
    regression = Criterion(
        name="reg", postconditions=(contains("ok"),), baseline=BaselineCount(951, 1000)
    )
    contract = ServiceContract(
        contract_id="two",
        invoke=exact_service(successes),  # type: ignore[arg-type]
        criteria=(compliance, regression),
    )
    return execute(contract, RunPlan(samples=100, inputs=("a",)))


class TestRequiredPass:
    """A criterion row states the count its rule decided by, as the engine decided it."""

    def test_each_row_carries_the_count_its_rule_decided_by(self, tmp_path: Path) -> None:
        result = two_criteria_result(93)
        text = render_verdict_record(result)
        rows = ElementTree.fromstring(text).findall(f"{NS}per-criterion/{NS}criterion")
        compliance, regression = (r.decision for r in result.criterion_results)
        assert isinstance(compliance, ComplianceVerdict)
        assert isinstance(regression, RegressionVerdict)
        assert [r.get("required-pass") for r in rows] == [
            str(compliance.minimum_passing),
            str(regression.cutoff),
        ]
        # The regression row is the interchange example's: the cutoff 91 of 100.
        assert rows[1].get("required-pass") == "91"
        assert_valid(tmp_path, text)

    @pytest.mark.parametrize("successes", [80, 85, 86, 87, 90, 91, 92, 100])
    def test_a_row_passes_exactly_when_it_reaches_its_required_count(self, successes: int) -> None:
        text = render_verdict_record(two_criteria_result(successes))
        rows = ElementTree.fromstring(text).findall(f"{NS}per-criterion/{NS}criterion")
        assert len(rows) == 2
        for row in rows:
            required = row.get("required-pass")
            assert required is not None
            reached = int(row.get("pass") or "") >= int(required)
            assert (row.get("verdict") == "PASS") is reached

    def test_no_count_is_stated_when_no_count_can_pass(self, tmp_path: Path) -> None:
        # A smoke test too small for its requirement still runs, and no count
        # of its size passes: k_min is undefined, so the row states none.
        contract = ServiceContract(
            contract_id="too-small",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="req", postconditions=(contains("ok"),), threshold=0.99),),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("a",), intent=Intent.SMOKE))
        decision = result.criterion_results[0].decision
        assert isinstance(decision, ComplianceVerdict) and decision.minimum_passing is None
        text = render_verdict_record(result)
        row = ElementTree.fromstring(text).find(f"{NS}per-criterion/{NS}criterion")
        assert row is not None and row.get("verdict") == "FAIL"
        assert row.get("required-pass") is None
        assert_valid(tmp_path, text)


class TestRefusedRecord:
    def test_a_refused_configuration_states_every_code_and_no_verdict(self, tmp_path: Path) -> None:
        compliance = Criterion(name="req", postconditions=(contains("ok"),), threshold=0.999)
        regression = Criterion(
            name="reg", postconditions=(contains("ok"),), baseline=BaselineCount(95, 100)
        )
        contract = ServiceContract(
            contract_id="refused", invoke=lambda v: "ok", criteria=(compliance, regression)
        )
        plan = RunPlan(samples=200, inputs=("a",))
        with pytest.raises(ConfigurationRefusedError) as refused:
            execute(contract, plan)
        text = render_refused_record(contract, plan, refused.value, "2026-09-28T10:00:00+00:00")
        root = ElementTree.fromstring(text)
        verdict = root.find(f"{NS}verdict")
        assert verdict is not None
        assert verdict.get("value") is None
        assert verdict.get("configuration-error") == (
            "TEST_LARGER_THAN_BASELINE COMPLIANCE_INFEASIBLE"
        )
        termination = root.find(f"{NS}termination")
        assert termination is not None and termination.get("reason") == "CONFIGURATION_REFUSED"
        execution = root.find(f"{NS}execution")
        assert execution is not None and execution.get("samples-executed") == "0"
        assert_valid(tmp_path, text)


class TestRunDesignRecording:
    def test_design_rides_the_schema_and_round_trips_through_the_reader(self) -> None:
        text = render_verdict_record(run_result(), RISK_DRIVEN_DESIGN)
        root = ElementTree.fromstring(text)
        baseline = root.find(f"{NS}baseline")
        assert baseline is not None
        assert baseline.get("samples") == "1000"
        assert baseline.get("source-file") == "sized-one-abc.yaml"
        environment = root.find(f"{NS}environment")
        assert environment is not None
        entries = {e.get("key"): e.get("value") for e in environment.findall(f"{NS}entry")}
        assert "sizing-approach" in entries
        assert "designAlternativeRate" in (entries.get("sizing-claim:keeps-up") or "")

        parsed = parse_verdict_record(text)
        assert parsed.design == RISK_DRIVEN_DESIGN

    def test_no_design_emits_no_baseline_and_no_sizing_entries(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(run_result()))
        assert root.find(f"{NS}baseline") is None
        # Since 1.3 the standings travel in their own element, so without a
        # recorded design there is no environment element at all.
        assert root.find(f"{NS}environment") is None
        assert parse_verdict_record(render_verdict_record(run_result())).design is None

    def test_designed_record_still_validates_against_the_family_xsd(self, tmp_path: Path) -> None:
        assert_valid(tmp_path, render_verdict_record(run_result(), RISK_DRIVEN_DESIGN))


class TestLatencyElement:
    def _result_with_latency(self, bar: LatencyBar, samples: int = 10) -> RunResult:
        contract = ServiceContract(
            contract_id="paced",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=bar,
        )
        return execute(contract, RunPlan(samples=samples, inputs=("a",), kind=RunKind.TEST))

    def test_explicit_bounds_emit_the_family_latency_element(self, tmp_path: Path) -> None:
        bar = LatencyBar(bounds=(LatencyBound("p50", 60_000),))
        text = render_verdict_record(self._result_with_latency(bar))
        root = ElementTree.fromstring(text)
        latency = root.find(f"{NS}latency")
        assert latency is not None
        assert latency.get("successful-samples") == "10"
        assert latency.get("strict-violations") == "0"
        assert latency.get("advisory-violations") == "0"
        assert latency.get("verdict") == "PASS"
        observed = latency.find(f"{NS}observed")
        assert observed is not None
        labels = [p.get("label") for p in observed.findall(f"{NS}percentile")]
        assert labels == ["p50", "p90"]  # gated at 10 contributing samples
        row = latency.find(f"{NS}evaluations/{NS}evaluation")
        assert row is not None
        assert row.get("percentile") == "p50"
        assert row.get("provenance") == "explicit"
        assert row.get("mode") == "strict"
        assert row.get("status") == "PASS"
        assert row.get("decision-rule") == "latency/compliance-exact-binomial"
        assert (row.get("within-threshold"), row.get("required-within")) == ("10", "9")
        assert row.get("baseline-rank") is None
        # Two rules decided the test: the verdict states none.
        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("decision-rule") is None
        assert_valid(tmp_path, text)

    def test_baseline_derived_bounds_carry_the_precedence_rank(self, tmp_path: Path) -> None:
        bar = LatencyBar(
            bounds=(LatencyBound("p50"),),
            origin=ThresholdSource.BASELINE_DERIVED,
            baseline=LatencyBaseline(tuple([60_000] * 56), samples=56),
        )
        text = render_verdict_record(self._result_with_latency(bar))
        root = ElementTree.fromstring(text)
        row = root.find(f"{NS}latency/{NS}evaluations/{NS}evaluation")
        assert row is not None
        assert row.get("provenance") == "baseline-derived"
        assert row.get("baseline-confidence") == "0.95"
        assert row.get("baseline-rank") is not None
        assert row.get("baseline-n") == "56"
        assert row.get("threshold-ms") == "60000"
        assert row.get("decision-rule") == "latency/precedence"
        assert_valid(tmp_path, text)

    def test_a_saturated_constraint_is_recorded_without_a_threshold(self, tmp_path: Path) -> None:
        # A p90 test of 10 against 32 baseline latencies: no rank achieves
        # alpha, so there is no threshold to state and none is manufactured.
        bar = LatencyBar(
            bounds=(LatencyBound("p90"),),
            origin=ThresholdSource.BASELINE_DERIVED,
            baseline=LatencyBaseline(tuple(range(1, 33)), samples=32),
        )
        text = render_verdict_record(self._result_with_latency(bar))
        root = ElementTree.fromstring(text)
        latency = root.find(f"{NS}latency")
        assert latency is not None and latency.get("verdict") == "INCONCLUSIVE"
        (row,) = latency.findall(f"{NS}evaluations/{NS}evaluation")
        assert row.get("status") == "SATURATED"
        assert row.get("provenance") == "baseline-derived"
        assert row.get("threshold-ms") is None
        assert row.get("baseline-rank") is None
        assert row.get("baseline-n") == "32"
        assert row.get("decision-rule") == "latency/precedence"
        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("value") == "INCONCLUSIVE"
        assert_valid(tmp_path, text)

    def test_no_latency_element_without_a_bar(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(run_result()))
        assert root.find(f"{NS}latency") is None
