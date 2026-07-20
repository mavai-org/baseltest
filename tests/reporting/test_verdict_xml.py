"""The canonical verdict record: family schema shape, mavai namespace."""

from pathlib import Path
from xml.etree import ElementTree

import baseltest
from baseltest.contract import Criterion, LatencyBar, LatencyBound, ServiceContract, contains
from baseltest.engine import Intent, RunKind, RunPlan, execute
from baseltest.reporting import (
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    parse_verdict_record,
    render_verdict_record,
    write_verdict_record,
)

NS = "{http://mavai.org/verdict/1.0}"

RISK_DRIVEN_DESIGN = RunDesign(
    approach="confidence-first (risk-driven)",
    claims=(
        ClaimDisclosure(
            criterion="keeps-up",
            baseline_rate=0.9,
            tolerated_rate=0.84,
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


def run_result():  # type: ignore[no-untyped-def]
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


class TestVerdictRecord:
    def test_record_shape(self) -> None:
        text = render_verdict_record(run_result())
        root = ElementTree.fromstring(text)
        assert root.tag == f"{NS}verdict-record"
        assert root.get("version") == "1.2"
        assert root.get("generator") == f"baseltest {baseltest.__version__}"

        identity = root.find(f"{NS}identity")
        assert identity is not None and identity.get("use-case-id") == "refund-confirmation"

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
        assert all(r.get("verdict") == "PASS" for r in rows[:1])
        composite = per_criterion.find(f"{NS}composite")
        assert composite is not None

        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("value") in ("PASS", "FAIL")

        covariates = root.find(f"{NS}covariates")
        assert covariates is not None and covariates.get("aligned") == "true"
        termination = root.find(f"{NS}termination")
        assert termination is not None and termination.get("reason") == "COMPLETED"

    def test_single_criterion_emits_statistics(self) -> None:
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

    def test_validates_against_the_family_xsd_when_xmllint_available(self, tmp_path: Path) -> None:
        import shutil
        import subprocess

        import pytest

        xmllint = shutil.which("xmllint")
        xsd = (
            Path(__file__).resolve().parents[3]
            / "punit/punit-report/src/main/resources/org/mavai/punit/report/verdict-1.2.xsd"
        )
        if xmllint is None or not xsd.is_file():
            pytest.skip("xmllint or the family XSD not available on this machine")
        record = tmp_path / "record.xml"
        record.write_text(render_verdict_record(run_result()), encoding="utf-8")
        completed = subprocess.run(
            [xmllint, "--noout", "--schema", str(xsd), str(record)],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


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
        keys = {e.get("key") for e in environment.findall(f"{NS}entry")}
        assert "sizing-approach" in keys
        assert "sizing-claim:keeps-up" in keys

        parsed = parse_verdict_record(text)
        assert parsed.design == RISK_DRIVEN_DESIGN

    def test_no_design_emits_no_baseline_or_environment(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(run_result()))
        assert root.find(f"{NS}baseline") is None
        assert root.find(f"{NS}environment") is None
        assert parse_verdict_record(render_verdict_record(run_result())).design is None

    def test_designed_record_still_validates_against_the_family_xsd(self, tmp_path: Path) -> None:
        import shutil
        import subprocess

        import pytest

        xmllint = shutil.which("xmllint")
        xsd = (
            Path(__file__).resolve().parents[3]
            / "punit/punit-report/src/main/resources/org/mavai/punit/report/verdict-1.2.xsd"
        )
        if xmllint is None or not xsd.is_file():
            pytest.skip("xmllint or the family XSD not available on this machine")
        record = tmp_path / "record.xml"
        record.write_text(render_verdict_record(run_result(), RISK_DRIVEN_DESIGN), encoding="utf-8")
        completed = subprocess.run(
            [xmllint, "--noout", "--schema", str(xsd), str(record)],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


class TestLatencyElement:
    def _result_with_latency(self, bar: LatencyBar):  # type: ignore[no-untyped-def]
        contract = ServiceContract(
            contract_id="paced",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=bar,
        )
        return execute(contract, RunPlan(samples=10, inputs=("a",), kind=RunKind.TEST))

    def test_explicit_bounds_emit_the_family_latency_element(self) -> None:
        bar = LatencyBar(bounds=(LatencyBound("p50", 60_000),), origin="explicit")
        root = ElementTree.fromstring(render_verdict_record(self._result_with_latency(bar)))
        latency = root.find(f"{NS}latency")
        assert latency is not None
        assert latency.get("successful-samples") == "10"
        assert latency.get("strict-violations") == "0"
        assert latency.get("advisory-violations") == "0"
        observed = latency.find(f"{NS}observed")
        assert observed is not None
        labels = [p.get("label") for p in observed.findall(f"{NS}percentile")]
        assert labels == ["p50", "p90"]  # gated at 10 contributing samples
        evaluations = latency.find(f"{NS}evaluations")
        assert evaluations is not None
        row = evaluations.findall(f"{NS}evaluation")[0]
        assert row.get("percentile") == "p50"
        assert row.get("provenance") == "explicit"
        assert row.get("mode") == "strict"
        assert row.get("status") == "PASS"
        assert row.get("baseline-rank") is None

    def test_baseline_derived_bounds_carry_derivation_attributes(self) -> None:
        bar = LatencyBar(
            bounds=(
                LatencyBound(
                    "p50",
                    60_000,
                    rank=35,
                    baseline_percentile_ms=10,
                    baseline_samples=56,
                ),
            ),
            origin="baseline-derived",
            confidence=0.95,
        )
        root = ElementTree.fromstring(render_verdict_record(self._result_with_latency(bar)))
        latency = root.find(f"{NS}latency")
        assert latency is not None
        evaluations = latency.find(f"{NS}evaluations")
        assert evaluations is not None
        row = evaluations.findall(f"{NS}evaluation")[0]
        assert row.get("provenance") == "baseline-derived"
        assert row.get("baseline-confidence") == "0.95"
        assert row.get("baseline-rank") == "35"
        assert row.get("baseline-n") == "56"

    def test_no_latency_element_without_a_bar(self) -> None:
        root = ElementTree.fromstring(render_verdict_record(run_result()))
        assert root.find(f"{NS}latency") is None
