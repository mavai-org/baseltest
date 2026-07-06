"""Honest-output shapes: verdicts with uncertainty; observations without verdict vocabulary."""

import re

import pytest

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import InfeasibleRunError, RunKind, RunPlan, execute
from baseltest.reporting import render_infeasible, render_run

VERDICT_VOCABULARY = ["PASS", "FAIL", "pass", "fail", "green", "red"]


def run_result(criteria: tuple[Criterion, ...], samples: int = 300, kind: RunKind = RunKind.TEST):  # type: ignore[no-untyped-def]
    contract = ServiceContract(
        contract_id="refund-confirmation",
        invoke=lambda value: f"refund ok for {value}",
        criteria=criteria,
    )
    return execute(contract, RunPlan(samples=samples, inputs=("a", "b"), kind=kind))


class TestVerdictOutput:
    def test_states_rate_bound_n_and_threshold(self) -> None:
        criterion = Criterion(name="relevant", postconditions=(contains("refund"),), threshold=0.95)
        text = render_run(run_result((criterion,)))
        assert "task refund-confirmation: PASS" in text
        assert "300 of 300 responses" in text
        assert "observed rate 1.0000" in text
        assert "confident the true rate is at least" in text
        assert "0.95 threshold" in text

    def test_multi_criterion_shape_lists_each_stream_and_composite(self) -> None:
        passing = Criterion(name="relevant", postconditions=(contains("refund"),), threshold=0.95)
        failing = Criterion(name="strict", postconditions=(contains("nope"),), threshold=0.5)
        text = render_run(run_result((passing, failing)))
        assert text.splitlines()[0] == "task refund-confirmation: FAIL"
        assert "criterion relevant: PASS" in text
        assert "criterion strict: FAIL" in text

    def test_mixed_contract_characterises_without_verdict_vocabulary_on_that_line(self) -> None:
        judged = Criterion(name="judged", postconditions=(contains("refund"),), threshold=0.95)
        measured = Criterion(name="measured", postconditions=(contains("ok"),))
        text = render_run(run_result((judged, measured)))
        measured_lines = [line for line in text.splitlines() if "measured" in line]
        assert measured_lines, text
        for line in measured_lines:
            assert not any(v in line for v in ("PASS", "FAIL"))
        assert "variance" in text

    def test_provenance_rendered_when_declared(self) -> None:
        from baseltest.contract import ThresholdProvenance

        criterion = Criterion(
            name="relevant",
            postconditions=(contains("refund"),),
            threshold=0.95,
            provenance=ThresholdProvenance(origin="sla", contract_ref="SLA v2 §4.1"),
        )
        text = render_run(run_result((criterion,)))
        assert "(sla, SLA v2 §4.1)" in text


class TestObservationOutput:
    def test_labelled_measurement_with_rate_and_variance_no_verdict_vocabulary(self) -> None:
        measured = Criterion(name="measured", postconditions=(contains("refund"),))
        text = render_run(run_result((measured,), samples=100, kind=RunKind.OBSERVATION))
        assert "OBSERVATION" in text
        assert "this is a measurement, not a verdict" in text
        assert "observed rate" in text and "variance" in text
        body = text.replace("OBSERVATION", "").replace("not a verdict", "")
        for word in VERDICT_VOCABULARY:
            assert not re.search(rf"\b{word}\b", body), f"verdict vocabulary {word!r} in: {text}"

    def test_baseline_path_named_when_persisted(self) -> None:
        measured = Criterion(name="measured", postconditions=(contains("refund"),))
        result = run_result((measured,), samples=50, kind=RunKind.MEASURE)
        text = render_run(result, baseline_path="baselines/refund.yaml")
        assert "baseline written: baselines/refund.yaml" in text


class TestInfeasibleOutput:
    def test_refusal_names_criterion_minimum_and_smoke(self) -> None:
        criterion = Criterion(name="sla", postconditions=(contains("x"),), threshold=0.99)
        contract = ServiceContract(
            contract_id="payment-meets-sla", invoke=lambda v: v, criteria=(criterion,)
        )
        with pytest.raises(InfeasibleRunError) as excinfo:
            execute(contract, RunPlan(samples=30, inputs=("a",)))
        text = render_infeasible("payment-meets-sla", excinfo.value)
        assert "cannot run as declared" in text
        assert "criterion sla" in text
        assert str(excinfo.value.governing_minimum) in text
        assert "intent: smoke" in text
