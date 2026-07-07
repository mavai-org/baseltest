"""The canonical verdict record: family schema shape, mavai namespace."""

from pathlib import Path
from xml.etree import ElementTree

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import Intent, RunKind, RunPlan, execute
from baseltest.reporting import render_verdict_record, write_verdict_record

NS = "{http://mavai.org/verdict/1.0}"


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
        assert "baseltest" in (root.get("generator") or "")

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
