"""A zero-failures criterion in the console, the verdict record and the
baseline artefact: a count of failed trials, never a rate, bound, threshold
or rule (§1.4.5; contract format §II.5)."""

import json
from itertools import count
from pathlib import Path
from xml.etree import ElementTree

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import RunKind, RunPlan, RunResult, execute
from baseltest.reporting import render_run, render_verdict_record

from .test_verdict_xml import NS, assert_valid

_BASELINE_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "conformance/interchange/mavai-baseline-1.schema.json"
    ).read_text(encoding="utf-8")
)


def _run(misses: int, kind: RunKind = RunKind.TEST, with_requirement: bool = False) -> RunResult:
    counter = count()
    criteria = [
        Criterion(name="never-insults", postconditions=(contains("ok"),), zero_failures=True)
    ]
    if with_requirement:
        criteria.append(Criterion(name="relevant", postconditions=(contains("ok"),), threshold=0.5))
    contract = ServiceContract(
        contract_id="greeting",
        invoke=lambda _value: "bad" if next(counter) < misses else "ok",
        criteria=tuple(criteria),
    )
    return execute(contract, RunPlan(samples=40, inputs=("a",), kind=kind))


class TestConsole:
    def test_a_pass_states_no_failure_observed_and_no_rate(self) -> None:
        text = render_run(_run(0))
        assert "no failure observed in 40 trials — no rate is claimed" in text
        row = next(line for line in text.splitlines() if "never-insults" in line)
        assert "PASS" in row and "zero failures" in row and "40/40" in row
        assert "observed rate" not in text
        assert "Clopper" not in text

    def test_a_fail_states_the_failed_trial_count(self) -> None:
        text = render_run(_run(2))
        assert "2 of 40 trials failed" in text

    def test_measure_records_the_count_without_verdict_vocabulary(self) -> None:
        text = render_run(_run(1, kind=RunKind.MEASURE))
        assert "criterion never-insults: recorded (zero failures declared)" in text
        assert "1 of 40 trials failed — recorded, not a verdict" in text
        assert "observed rate" not in text
        assert "PASS" not in text and "FAIL" not in text


class TestVerdictRecord:
    def _row(self, text: str) -> ElementTree.Element:
        root = ElementTree.fromstring(text)
        row = root.find(f"{NS}per-criterion/{NS}criterion[@id='never-insults']")
        assert row is not None
        return row

    def test_the_row_states_counts_only(self, tmp_path: Path) -> None:
        text = render_verdict_record(_run(0))
        row = self._row(text)
        assert row.get("verdict") == "PASS"
        assert (row.get("pass"), row.get("fail"), row.get("total")) == ("40", "0", "40")
        for absent in (
            "observed-rate",
            "threshold",
            "decision-rule",
            "decision-rule-version",
            "required-pass",
        ):
            assert row.get(absent) is None, absent
        root = ElementTree.fromstring(text)
        assert root.find(f"{NS}statistics") is None
        verdict = root.find(f"{NS}verdict")
        assert verdict is not None and verdict.get("decision-rule") is None
        assert_valid(tmp_path, text)

    def test_beside_a_requirement_the_record_still_validates(self, tmp_path: Path) -> None:
        text = render_verdict_record(_run(1, with_requirement=True))
        assert self._row(text).get("verdict") == "FAIL"
        assert_valid(tmp_path, text)


class TestBaseline:
    def test_the_criterion_is_recorded_as_observational(self, tmp_path: Path) -> None:
        record = BaselineRecord.from_run_result(_run(1, kind=RunKind.MEASURE), "greeter")
        path = write_baseline(record, tmp_path)
        document = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
        Draft202012Validator(_BASELINE_SCHEMA).validate(document)
        criterion = document["criteria"]["never-insults"]
        assert criterion["mode"] == "observational"
        assert (criterion["trials"], criterion["successes"]) == (40, 39)
        for absent in ("procedure", "observedPassRate", "wilsonLowerBound", "normativeJudgement"):
            assert absent not in criterion, absent
