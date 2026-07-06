"""The reader end-to-end: parse, validate, instantiate, run, persist, refuse."""

from pathlib import Path

import pytest

from baseltest.declarative import binding, check, run, transform
from baseltest.declarative._errors import TaskConfigurationError
from baseltest.declarative._materialise import materialise
from baseltest.declarative._parser import load_task, parse_task
from baseltest.declarative._registry import clear_registries
from baseltest.engine import InfeasibleRunError
from baseltest.statistics.verdict import Verdict


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


def write_task(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "task.yaml"
    path.write_text(text, encoding="utf-8")
    return path


GREETING_TASK = """
format: mavai-task/1
task: greeting-service-is-polite
service: greeting-service
samples: 100
inputs:
  - "Alice"
  - "Bob"
criteria:
  - threshold: 0.5
    contains: "hello"
"""


class TestFirstContactPath:
    def test_zero_to_verdict(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        result = run(write_task(tmp_path, GREETING_TASK))
        assert result.composite is Verdict.PASS
        out = capsys.readouterr().out
        assert "task greeting-service-is-polite: PASS" in out

    def test_unregistered_binding_refused_with_zero_invocations(self, tmp_path: Path) -> None:
        with pytest.raises(TaskConfigurationError) as excinfo:
            run(write_task(tmp_path, GREETING_TASK))
        assert "greeting-service" in str(excinfo.value)
        assert "@binding" in str(excinfo.value)

    def test_derived_samples_stated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace("samples: 100\n", "")
        result = run(write_task(tmp_path, task))
        assert "derived" in capsys.readouterr().out
        from baseltest.statistics import check_feasibility

        assert result.plan.samples == check_feasibility(1, 0.5, 0.95).minimum_samples


class TestValidationRefusals:
    def test_reserved_key_rejected_with_pointer(self, tmp_path: Path) -> None:
        task = GREETING_TASK + "covariates:\n  model: x\n"
        with pytest.raises(TaskConfigurationError) as excinfo:
            load_task(write_task(tmp_path, task))
        assert "reserved" in str(excinfo.value)
        assert "extension seams" in str(excinfo.value)

    def test_reserved_kind_rejected(self) -> None:
        with pytest.raises(TaskConfigurationError, match="reserved"):
            parse_task(GREETING_TASK + "kind: explore\n")

    def test_unknown_key_named(self) -> None:
        with pytest.raises(TaskConfigurationError, match="samplez"):
            parse_task(GREETING_TASK + "samplez: 3\n")

    def test_kind_test_without_threshold_is_a_contradiction(self) -> None:
        task = (
            GREETING_TASK.replace("- threshold: 0.5\n    contains", "- contains") + "kind: test\n"
        )
        with pytest.raises(TaskConfigurationError, match="needs a bar"):
            parse_task(task)

    def test_samples_required_without_threshold(self) -> None:
        task = GREETING_TASK.replace("- threshold: 0.5\n    contains", "- contains").replace(
            "samples: 100\n", ""
        )
        with pytest.raises(TaskConfigurationError, match="feasibility anchor"):
            parse_task(task)

    def test_transform_and_parses_are_exclusive(self) -> None:
        task = GREETING_TASK.replace(
            'contains: "hello"', 'contains: "hello"\n    transform: json\n    parses: json'
        )
        with pytest.raises(TaskConfigurationError, match="at most one"):
            parse_task(task)

    def test_path_requires_stock_transform(self) -> None:
        task = """
format: mavai-task/1
task: t
service: s
samples: 10
inputs: ["a"]
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
"""
        with pytest.raises(TaskConfigurationError, match="stock transform"):
            parse_task(task)

    def test_bad_jsonpath_refused_at_load(self, tmp_path: Path) -> None:
        @binding("s")
        def invoke(value: str) -> str:
            return value

        task = """
format: mavai-task/1
task: t
service: s
samples: 100
inputs: ["a"]
criteria:
  - threshold: 0.5
    transform: json
    postconditions:
      - path: "$[["
        equals: "1"
"""
        with pytest.raises(TaskConfigurationError, match="JSONPath"):
            run(write_task(tmp_path, task))

    def test_expected_pairs_require_single_criterion(self) -> None:
        task = """
format: mavai-task/1
task: t
service: s
samples: 10
inputs:
  - { input: "a", expected: { contains: "A" } }
criteria:
  - threshold: 0.5
    contains: "x"
  - threshold: 0.6
    contains: "y"
"""
        with pytest.raises(TaskConfigurationError, match="ambiguous"):
            parse_task(task)

    def test_infeasible_verification_run_is_refused(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace("threshold: 0.5", "threshold: 0.99").replace(
            "samples: 100", "samples: 30"
        )
        with pytest.raises(InfeasibleRunError):
            run(write_task(tmp_path, task))


class TestStructuredResponses:
    def test_json_path_checks(self, tmp_path: Path) -> None:
        @binding("refund-service")
        def refund(value: str) -> str:
            return '{"refund": {"id": "RF-12345678"}, "status": "CONFIRMED"}'

        task = """
format: mavai-task/1
task: refund-confirmation
service: refund-service
samples: 100
inputs: ["order 1"]
criteria:
  - threshold: 0.5
    transform: json
    postconditions:
      - path: "$.refund.id"
        matches: "RF-\\\\d{8}"
      - path: "$.status"
        equals: "CONFIRMED"
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS

    def test_empty_selection_fails_the_trial(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return '{"other": 1}'

        task = """
format: mavai-task/1
task: t
service: svc
samples: 100
inputs: ["a"]
criteria:
  - threshold: 0.5
    transform: json
    postconditions:
      - path: "$.missing"
        equals: "x"
"""
        result = run(write_task(tmp_path, task), emit=False)
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any("selected nothing" in r for r in tally.failure_reasons)

    def test_yaml_transform_norway_projection(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "country: no"

        task = """
format: mavai-task/1
task: t
service: svc
samples: 100
inputs: ["a"]
criteria:
  - threshold: 0.5
    transform: yaml
    postconditions:
      - path: "$.country"
        equals: "no"
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS

    def test_unparseable_response_is_a_transform_failure_not_an_abort(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "not json"

        task = """
format: mavai-task/1
task: t
service: svc
samples: 100
inputs: ["a"]
criteria:
  - threshold: 0.5
    parses: json
"""
        result = run(write_task(tmp_path, task), emit=False)
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any(r.startswith("transform failed") for r in tally.failure_reasons)

    def test_registered_transform_and_check(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return f"value={value}"

        @transform("key-value")
        def parse_kv(raw: str) -> dict[str, str]:
            key, _, val = raw.partition("=")
            return {key: val}

        @check("has-value")
        def has_value(parsed: dict[str, str]) -> bool:
            return "value" in parsed

        task = """
format: mavai-task/1
task: t
service: svc
samples: 100
inputs: ["a"]
criteria:
  - threshold: 0.5
    transform: key-value
    satisfies: has-value
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS


class TestMeasureAndPairs:
    def test_measure_persists_baseline_before_returning(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "hello"

        task = """
format: mavai-task/1
task: measured-task
service: svc
samples: 50
inputs: ["a"]
kind: measure
criteria:
  - contains: "hello"
"""
        run(write_task(tmp_path, task), baseline_dir=tmp_path / "b", emit=False)
        artefacts = list((tmp_path / "b").glob("measured-task-*.yaml"))
        assert len(artefacts) == 1
        content = artefacts[0].read_text(encoding="utf-8")
        assert "baseltest-baseline-1" in content
        assert "mavai-task/1" in content

    def test_thresholded_measure_records_judgement(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "hello"

        task = """
format: mavai-task/1
task: gated-measure
service: svc
samples: 100
inputs: ["a"]
kind: measure
criteria:
  - threshold: 0.5
    contains: "hello"
"""
        result = run(write_task(tmp_path, task), baseline_dir=tmp_path / "b", emit=False)
        assert result.composite is Verdict.PASS
        content = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")
        assert "normativeJudgement" in content
        assert '"met"' in content

    def test_expected_pairs_dispatch_per_input(self, tmp_path: Path) -> None:
        @binding("capitals")
        def capitals(value: str) -> str:
            return {"France?": "Paris.", "Italy?": "Rome."}[value]

        task = """
format: mavai-task/1
task: capitals
service: capitals
samples: 100
inputs:
  - { input: "France?", expected: { contains: "Paris" } }
  - { input: "Italy?", expected: { contains: "Rome" } }
criteria:
  - threshold: 0.5
    matches: "."
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS


class TestMaterialisation:
    def test_emits_python_for_the_same_contract(self, tmp_path: Path) -> None:
        declaration = load_task(write_task(tmp_path, GREETING_TASK))
        source = materialise(declaration)
        assert "ServiceContract(" in source
        assert "contains('hello')" in source or 'contains("hello")' in source
        assert "threshold=0.5" in source
        assert "greeting-service" in source
        compile(source, "materialised.py", "exec")
