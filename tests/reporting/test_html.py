"""The probabilistic-test summary: self-contained, test-runs-only, escapes untrusted text."""

from pathlib import Path

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.declarative import binding, run
from baseltest.declarative._registry import clear_registries
from baseltest.engine import RunKind, RunPlan, execute
from baseltest.reporting import render_html_report


def result_for(criteria: tuple[Criterion, ...], kind: RunKind = RunKind.TEST):  # type: ignore[no-untyped-def]
    contract = ServiceContract(
        contract_id="refund-confirmation",
        invoke=lambda value: f"refund ok <b>{value}</b>",
        criteria=criteria,
    )
    return execute(contract, RunPlan(samples=100, inputs=("a",), kind=kind))


class TestHtmlReport:
    def test_self_contained_single_file(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("refund"),), threshold=0.5)
        page = render_html_report(result_for((criterion,)))
        assert page.startswith("<!DOCTYPE html>")
        for external in ("<script", "src=", "href="):
            assert external not in page
        assert "<style>" in page

    def test_verdict_content_states_bound_threshold_and_n(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("refund"),), threshold=0.5)
        page = render_html_report(result_for((criterion,)))
        assert "PASS" in page
        assert "100/100" in page
        assert "lower bound" in page
        assert "0.5" in page

    def test_non_test_runs_have_no_report(self) -> None:
        import pytest

        criterion = Criterion(name="measured", postconditions=(contains("refund"),))
        with pytest.raises(ValueError, match="baseline artefact"):
            render_html_report(result_for((criterion,), kind=RunKind.MEASURE))

    def test_failure_distribution_in_details_element(self) -> None:
        judged = Criterion(name="ok", postconditions=(contains("refund"),), threshold=0.5)
        never = Criterion(name="never", postconditions=(contains("nope"),))
        page = render_html_report(result_for((judged, never)))
        assert "<details>" in page
        assert "failure distribution" in page

    def test_untrusted_text_is_escaped(self) -> None:
        criterion = Criterion(
            name="x<script>alert(1)</script>",
            postconditions=(contains("<b>"),),
            threshold=0.5,
        )
        page = render_html_report(result_for((criterion,)))
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_cli_writes_report_file(self, tmp_path: Path) -> None:
        clear_registries()
        try:

            @binding("svc")
            def invoke(value: str) -> str:
                return "hello"

            task = tmp_path / "task.yaml"
            task.write_text(
                """
format: mavai-task/1
task: report-me
service: svc
samples: 50
inputs: ["a"]
criteria:
  - threshold: 0.5
    contains: "hello"
""",
                encoding="utf-8",
            )
            report = tmp_path / "out" / "report.html"
            run(task, html_report=report, emit=False)
            page = report.read_text(encoding="utf-8")
            assert "report-me" in page
            assert "PASS" in page
        finally:
            clear_registries()
