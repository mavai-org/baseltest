"""The reader end-to-end: parse, validate, instantiate per mode, run, persist, refuse."""

from pathlib import Path

import pytest

from baseltest.declarative import binding, check, run, transform
from baseltest.declarative._errors import TaskConfigurationError
from baseltest.declarative._materialise import materialise
from baseltest.declarative._parser import load_task, parse_task
from baseltest.declarative._registry import clear_registries
from baseltest.engine import InfeasibleRunError, Verdict


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
criteria:
  - threshold: 0.5
    contains: "hello"
inputs:
  - "Alice"
  - "Bob"
"""

TWO_CRITERIA = (
    'criteria:\n  - name: judged\n    threshold: 0.5\n    contains: "hello"\n'
    '  - name: watched\n    contains: "Alice"'
)


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


class TestRunModes:
    def test_kind_key_withdrawn_with_pointer_to_the_verbs(self) -> None:
        with pytest.raises(TaskConfigurationError, match="invocation verb"):
            parse_task(GREETING_TASK + "kind: measure\n")

    def test_test_mode_without_thresholds_is_refused(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace("- threshold: 0.5\n    contains", "- contains")
        with pytest.raises(TaskConfigurationError, match="nothing to test"):
            run(write_task(tmp_path, task), mode="test")

    def test_test_mode_skips_unthresholded_criteria_with_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace(
            'criteria:\n  - threshold: 0.5\n    contains: "hello"', TWO_CRITERIA
        )
        result = run(write_task(tmp_path, task), mode="test")
        assert [r.name for r in result.criterion_results] == ["judged"]
        out = capsys.readouterr().out
        assert "criterion watched declares no threshold and was not judged" in out
        assert "baseltest measure" in out

    def test_measure_mode_records_all_and_persists(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace(
            'criteria:\n  - threshold: 0.5\n    contains: "hello"', TWO_CRITERIA
        )
        result = run(
            write_task(tmp_path, task), mode="measure", baseline_dir=tmp_path / "b", emit=False
        )
        assert {r.name for r in result.criterion_results} == {"judged", "watched"}
        artefacts = list((tmp_path / "b").glob("*.yaml"))
        assert len(artefacts) == 1
        content = artefacts[0].read_text(encoding="utf-8")
        assert '"runMode": "measure"' in content
        assert '"watched"' in content

    def test_measure_without_thresholds_requires_samples(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        task = GREETING_TASK.replace("- threshold: 0.5\n    contains", "- contains").replace(
            "samples: 100\n", ""
        )
        with pytest.raises(TaskConfigurationError, match="feasibility anchor"):
            run(write_task(tmp_path, task), mode="measure", emit=False)

    def test_measure_run_refuses_html_report(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        with pytest.raises(TaskConfigurationError, match="baseline artefact"):
            run(
                write_task(tmp_path, GREETING_TASK),
                mode="measure",
                html_report=tmp_path / "r.html",
                emit=False,
            )


class TestValidationRefusals:
    def test_reserved_key_rejected_with_pointer(self, tmp_path: Path) -> None:
        task = GREETING_TASK + "covariates:\n  model: x\n"
        with pytest.raises(TaskConfigurationError) as excinfo:
            load_task(write_task(tmp_path, task))
        assert "reserved" in str(excinfo.value)
        assert "extension seams" in str(excinfo.value)

    def test_unknown_key_named(self) -> None:
        with pytest.raises(TaskConfigurationError, match="samplez"):
            parse_task(GREETING_TASK + "samplez: 3\n")

    def test_criterion_level_transform_directed_to_the_views_block(self) -> None:
        task = GREETING_TASK.replace('contains: "hello"', 'contains: "hello"\n    transform: json')
        with pytest.raises(TaskConfigurationError, match="transforms:"):
            parse_task(task)

    def test_raw_view_reserved(self) -> None:
        task = GREETING_TASK + "transforms:\n  raw: json\n"
        with pytest.raises(TaskConfigurationError, match="reserved name"):
            parse_task(task)

    def test_in_names_a_declared_view(self) -> None:
        task = """
format: mavai-task/1
task: t
service: s
samples: 10
criteria:
  - threshold: 0.5
    postconditions:
      - in: ghost
        contains: "x"
inputs: ["a"]
"""
        with pytest.raises(TaskConfigurationError, match="undeclared view"):
            parse_task(task)

    def test_path_requires_a_stock_transformed_view(self) -> None:
        task = """
format: mavai-task/1
task: t
service: s
samples: 10
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        with pytest.raises(TaskConfigurationError, match="stock"):
            parse_task(task)

    def test_parses_references_a_declared_view(self) -> None:
        task = GREETING_TASK.replace('contains: "hello"', "parses: json")
        with pytest.raises(TaskConfigurationError, match="declared view"):
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
transforms:
  doc: json
criteria:
  - threshold: 0.5
    postconditions:
      - in: doc
        path: "$[["
        equals: "1"
inputs: ["a"]
"""
        with pytest.raises(TaskConfigurationError, match="JSONPath"):
            run(write_task(tmp_path, task))

    def test_expected_entries_require_single_criterion(self) -> None:
        task = """
format: mavai-task/1
task: t
service: s
samples: 10
criteria:
  - threshold: 0.5
    contains: "x"
  - threshold: 0.6
    contains: "y"
inputs:
  - { input: "a", expected: { contains: "A" } }
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


class TestViewsEndToEnd:
    def test_views_and_paths(self, tmp_path: Path) -> None:
        @binding("refund-service")
        def refund(value: str) -> str:
            return '{"refund": {"id": "RF-12345678"}, "status": "CONFIRMED"}'

        task = """
format: mavai-task/1
task: refund-confirmation
service: refund-service
samples: 100
transforms:
  doc: json
criteria:
  - threshold: 0.5
    postconditions:
      - in: doc
        path: "$.refund.id"
        matches: "RF-\\\\d{8}"
      - in: doc
        path: "$.status"
        equals: "CONFIRMED"
inputs: ["order 1"]
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
transforms:
  doc: json
criteria:
  - threshold: 0.5
    postconditions:
      - in: doc
        path: "$.missing"
        equals: "x"
inputs: ["a"]
"""
        result = run(write_task(tmp_path, task), emit=False)
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any("selected nothing" in r for r in tally.failure_reasons)

    def test_parses_forces_the_view(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "not json"

        task = """
format: mavai-task/1
task: t
service: svc
samples: 100
transforms:
  doc: json
criteria:
  - threshold: 0.5
    parses: doc
inputs: ["a"]
"""
        result = run(write_task(tmp_path, task), emit=False)
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any(r.startswith("transform failed") for r in tally.failure_reasons)

    def test_registered_transformation_and_check(self, tmp_path: Path) -> None:
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
transforms:
  kv: key-value
criteria:
  - threshold: 0.5
    postconditions:
      - in: kv
        satisfies: has-value
inputs: ["a"]
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS


class TestPerInputExpectations:
    def test_expected_lists_dispatch_per_input_with_views(self, tmp_path: Path) -> None:
        @binding("baskets")
        def baskets(value: str) -> str:
            item = "egg" if "egg" in value else "milk"
            quantity = 6 if item == "egg" else 2
            return f'{{"items": [{{"name": "{item}", "quantity": {quantity}}}]}}'

        task = """
format: mavai-task/1
task: basket-per-input
service: baskets
samples: 100
transforms:
  basket: json
criteria:
  - threshold: 0.9
    postconditions:
      - in: basket
        path: "$.items[*].name"
        matches: '\\w'
inputs:
  - input: "place 6 eggs in the basket"
    expected:
      - in: basket
        path: "$.items[*].name"
        contains: "egg"
      - in: basket
        path: "$.items[*].quantity"
        equals: "6"
  - input: "two bottles of milk"
    expected: { contains: "milk" }
"""
        result = run(write_task(tmp_path, task), emit=False)
        assert result.composite is Verdict.PASS

    def test_wrong_expectation_fails_only_its_input_trials(self, tmp_path: Path) -> None:
        @binding("echo")
        def echo(value: str) -> str:
            return value

        task = """
format: mavai-task/1
task: t
service: echo
samples: 100
criteria:
  - threshold: 0.9
    matches: "."
inputs:
  - input: "good"
    expected: { contains: "good" }
  - input: "bad"
    expected: { contains: "impossible" }
"""
        result = run(write_task(tmp_path, task), emit=False)
        tally = result.criterion_results[0].tally
        assert 0 < tally.successes < tally.trials  # 'good' trials pass, 'bad' fail


class TestMaterialisation:
    def test_emits_python_for_the_same_contract(self, tmp_path: Path) -> None:
        declaration = load_task(write_task(tmp_path, GREETING_TASK))
        source = materialise(declaration)
        assert "ServiceContract(" in source
        assert "contains('hello')" in source or 'contains("hello")' in source
        assert "threshold=0.5" in source
        assert "greeting-service" in source
        compile(source, "materialised.py", "exec")
