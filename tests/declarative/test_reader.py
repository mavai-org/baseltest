"""The reader end-to-end: parse, validate, instantiate per mode, run, persist, refuse."""

from pathlib import Path

import pytest

from baseltest.declarative import binding, check, run, transform
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._materialise import materialise
from baseltest.declarative._parser import load_contract, parse_contract
from baseltest.declarative._registry import clear_registries
from baseltest.engine import InfeasibleRunError, Verdict


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


def write_contract(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


GREETING_CONTRACT = """
format: mavai-contract/1
contract: greeting-service-is-polite
service: greeting-service
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

        result = run(write_contract(tmp_path, GREETING_CONTRACT))
        assert result.composite is Verdict.PASS
        out = capsys.readouterr().out
        assert "contract greeting-service-is-polite: PASS" in out

    def test_unregistered_binding_refused_with_zero_invocations(self, tmp_path: Path) -> None:
        with pytest.raises(ContractConfigurationError) as excinfo:
            run(write_contract(tmp_path, GREETING_CONTRACT))
        assert "greeting-service" in str(excinfo.value)
        assert "@binding" in str(excinfo.value)

    def test_derived_samples_stated_in_the_run_plan_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        result = run(write_contract(tmp_path, GREETING_CONTRACT))
        out = capsys.readouterr().out
        assert "derived" in out and f"n = {result.plan.samples}" in out
        from baseltest.statistics import check_feasibility

        assert result.plan.samples == check_feasibility(1, 0.5, 0.95).minimum_samples

    def test_a_withdrawn_sizing_key_is_refused_naming_the_flag(self) -> None:
        with pytest.raises(ContractConfigurationError, match="--samples"):
            parse_contract(GREETING_CONTRACT + "samples: 100\n")
        with pytest.raises(ContractConfigurationError, match="--samples-per-config"):
            parse_contract(GREETING_CONTRACT + "samples-per-config: 3\n")


class TestRunModes:
    def test_kind_key_withdrawn_with_pointer_to_the_verbs(self) -> None:
        with pytest.raises(ContractConfigurationError, match="invocation verb"):
            parse_contract(GREETING_CONTRACT + "kind: measure\n")

    def test_test_mode_without_thresholds_is_refused(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        contract = GREETING_CONTRACT.replace("- threshold: 0.5\n    contains", "- contains")
        with pytest.raises(ContractConfigurationError, match="nothing to test"):
            run(write_contract(tmp_path, contract), mode="test")

    def test_test_mode_skips_unthresholded_criteria_with_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        contract = GREETING_CONTRACT.replace(
            'criteria:\n  - threshold: 0.5\n    contains: "hello"', TWO_CRITERIA
        )
        result = run(write_contract(tmp_path, contract), mode="test")
        assert [r.name for r in result.criterion_results] == ["judged"]
        out = capsys.readouterr().out
        assert "empirical criterion watched: no baseline found" in out
        assert "baseltest measure" in out

    def test_measure_mode_records_all_and_persists(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        contract = GREETING_CONTRACT.replace(
            'criteria:\n  - threshold: 0.5\n    contains: "hello"', TWO_CRITERIA
        )
        result = run(
            write_contract(tmp_path, contract),
            mode="measure",
            samples=30,
            baseline_dir=tmp_path / "b",
            emit=False,
        )
        assert {r.name for r in result.criterion_results} == {"judged", "watched"}
        artefacts = list((tmp_path / "b").glob("*.yaml"))
        assert len(artefacts) == 1
        content = artefacts[0].read_text(encoding="utf-8")
        assert '"runMode": "measure"' in content
        assert '"watched"' in content

    def test_measure_requires_an_explicit_sample_count(self, tmp_path: Path) -> None:
        # The old file-side rule, relocated: a measurement's budget is an
        # experimental-design decision, so it must be typed.
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        with pytest.raises(ContractConfigurationError, match="--samples") as refusal:
            run(write_contract(tmp_path, GREETING_CONTRACT), mode="measure", emit=False)
        assert "baseline-grade" in str(refusal.value)  # 1,000 recommended, visibly

    def test_measure_run_refuses_html_report(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        with pytest.raises(ContractConfigurationError, match="baseline artefact"):
            run(
                write_contract(tmp_path, GREETING_CONTRACT),
                mode="measure",
                samples=10,
                html_report=tmp_path / "r.html",
                emit=False,
            )


class TestValidationRefusals:
    def test_reserved_key_rejected_with_pointer(self, tmp_path: Path) -> None:
        contract = GREETING_CONTRACT + "covariates:\n  model: x\n"
        with pytest.raises(ContractConfigurationError) as excinfo:
            load_contract(write_contract(tmp_path, contract))
        assert "reserved" in str(excinfo.value)
        assert "extension seams" in str(excinfo.value)

    def test_unknown_key_named(self) -> None:
        with pytest.raises(ContractConfigurationError, match="samplez"):
            parse_contract(GREETING_CONTRACT + "samplez: 3\n")

    def test_criterion_level_transform_directed_to_the_views_block(self) -> None:
        contract = GREETING_CONTRACT.replace(
            'contains: "hello"', 'contains: "hello"\n    transform: json'
        )
        with pytest.raises(ContractConfigurationError, match="transforms:"):
            parse_contract(contract)

    def test_raw_view_reserved(self) -> None:
        contract = GREETING_CONTRACT + "transforms:\n  raw: json\n"
        with pytest.raises(ContractConfigurationError, match="reserved name"):
            parse_contract(contract)

    def test_in_names_a_declared_view(self) -> None:
        contract = """
format: mavai-contract/1
contract: t
service: s
criteria:
  - threshold: 0.5
    postconditions:
      - in: ghost
        contains: "x"
inputs: ["a"]
"""
        with pytest.raises(ContractConfigurationError, match="undeclared view"):
            parse_contract(contract)

    def test_path_requires_a_stock_transformed_view(self) -> None:
        contract = """
format: mavai-contract/1
contract: t
service: s
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        with pytest.raises(ContractConfigurationError, match="stock"):
            parse_contract(contract)

    def test_parses_references_a_declared_view(self) -> None:
        contract = GREETING_CONTRACT.replace('contains: "hello"', "parses: json")
        with pytest.raises(ContractConfigurationError, match="declared view"):
            parse_contract(contract)

    def test_bad_jsonpath_refused_at_load(self, tmp_path: Path) -> None:
        @binding("s")
        def invoke(value: str) -> str:
            return value

        contract = """
format: mavai-contract/1
contract: t
service: s
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
        with pytest.raises(ContractConfigurationError, match="JSONPath"):
            run(write_contract(tmp_path, contract))

    def test_expected_entries_require_single_criterion(self) -> None:
        contract = """
format: mavai-contract/1
contract: t
service: s
criteria:
  - threshold: 0.5
    contains: "x"
  - threshold: 0.6
    contains: "y"
inputs:
  - { input: "a", expected: { contains: "A" } }
"""
        with pytest.raises(ContractConfigurationError, match="ambiguous"):
            parse_contract(contract)

    def test_infeasible_verification_run_is_refused(self, tmp_path: Path) -> None:
        @binding("greeting-service")
        def greet(value: str) -> str:
            return f"hello {value}"

        contract = GREETING_CONTRACT.replace("threshold: 0.5", "threshold: 0.99")
        with pytest.raises(InfeasibleRunError):
            run(write_contract(tmp_path, contract), samples=30)


class TestViewsEndToEnd:
    def test_views_and_paths(self, tmp_path: Path) -> None:
        @binding("refund-service")
        def refund(value: str) -> str:
            return '{"refund": {"id": "RF-12345678"}, "status": "CONFIRMED"}'

        contract = """
format: mavai-contract/1
contract: refund-confirmation
service: refund-service
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
        result = run(write_contract(tmp_path, contract), emit=False)
        assert result.composite is Verdict.PASS

    def test_empty_selection_fails_the_trial(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return '{"other": 1}'

        contract = """
format: mavai-contract/1
contract: t
service: svc
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
        result = run(write_contract(tmp_path, contract), emit=False)
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any("selected nothing" in r for r in tally.failure_reasons)

    def test_parses_forces_the_view(self, tmp_path: Path) -> None:
        @binding("svc")
        def invoke(value: str) -> str:
            return "not json"

        contract = """
format: mavai-contract/1
contract: t
service: svc
transforms:
  doc: json
criteria:
  - threshold: 0.5
    parses: doc
inputs: ["a"]
"""
        result = run(write_contract(tmp_path, contract), emit=False)
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

        contract = """
format: mavai-contract/1
contract: t
service: svc
transforms:
  kv: key-value
criteria:
  - threshold: 0.5
    postconditions:
      - in: kv
        satisfies: has-value
inputs: ["a"]
"""
        result = run(write_contract(tmp_path, contract), emit=False)
        assert result.composite is Verdict.PASS


class TestPerInputExpectations:
    def test_expected_lists_dispatch_per_input_with_views(self, tmp_path: Path) -> None:
        @binding("baskets")
        def baskets(value: str) -> str:
            item = "egg" if "egg" in value else "milk"
            quantity = 6 if item == "egg" else 2
            return f'{{"items": [{{"name": "{item}", "quantity": {quantity}}}]}}'

        contract = """
format: mavai-contract/1
contract: basket-per-input
service: baskets
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
        result = run(write_contract(tmp_path, contract), emit=False)
        assert result.composite is Verdict.PASS

    def test_wrong_expectation_fails_only_its_input_trials(self, tmp_path: Path) -> None:
        @binding("echo")
        def echo(value: str) -> str:
            return value

        contract = """
format: mavai-contract/1
contract: t
service: echo
criteria:
  - threshold: 0.9
    matches: "."
inputs:
  - input: "good"
    expected: { contains: "good" }
  - input: "bad"
    expected: { contains: "impossible" }
"""
        result = run(write_contract(tmp_path, contract), emit=False)
        tally = result.criterion_results[0].tally
        assert 0 < tally.successes < tally.trials  # 'good' trials pass, 'bad' fail


class TestMaterialisation:
    def test_emits_python_for_the_same_contract(self, tmp_path: Path) -> None:
        declaration = load_contract(write_contract(tmp_path, GREETING_CONTRACT))
        source = materialise(declaration)
        assert "ServiceContract(" in source
        assert "contains('hello')" in source or 'contains("hello")' in source
        assert "threshold=0.5" in source
        assert "greeting-service" in source
        compile(source, "materialised.py", "exec")


class TestEmpiricalJudgement:
    CONTRACT = """
format: mavai-contract/1
contract: ratchet
service: svc
criteria:
  - name: keeps-up
    contains: "ok"
inputs: ["a", "b"]
"""

    def _bind(self):  # type: ignore[no-untyped-def]
        @binding("svc")
        def invoke(value: str) -> str:
            return f"ok {value}"

    def test_measure_then_test_judges_empirically(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._bind()
        contract = write_contract(tmp_path, self.CONTRACT)
        run(contract, mode="measure", samples=200, baseline_dir=tmp_path / "baselines", emit=False)
        result = run(contract, mode="test", samples=200, baseline_dir=tmp_path / "baselines")
        assert result.composite is Verdict.PASS
        judged = result.criterion_results[0]
        assert judged.criterion.provenance.origin == "empirical"
        assert judged.criterion.provenance.contract_ref is not None
        assert judged.criterion.provenance.contract_ref.endswith(".yaml")
        out = capsys.readouterr().out
        assert "empirical" in out and ".yaml" in out
        # the bar is the companion's sample-size-first derivation at this N
        from baseltest.statistics import derive_sample_size_first

        expected = derive_sample_size_first(200, 200, 200, 0.95).min_pass_rate
        assert judged.criterion.threshold == pytest.approx(expected)

    def test_baseline_criterion_missing_skips_with_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._bind()
        contract = write_contract(tmp_path, self.CONTRACT)
        run(contract, mode="measure", samples=200, baseline_dir=tmp_path / "baselines", emit=False)
        renamed = self.CONTRACT.replace("name: keeps-up", "name: renamed-criterion")
        with pytest.raises(ContractConfigurationError, match="does not record"):
            run(
                write_contract(tmp_path, renamed),
                mode="test",
                baseline_dir=tmp_path / "baselines",
            )

    def test_empirical_only_test_without_baseline_is_refused(self, tmp_path: Path) -> None:
        self._bind()
        with pytest.raises(ContractConfigurationError, match="nothing to test"):
            run(
                write_contract(tmp_path, self.CONTRACT),
                mode="test",
                baseline_dir=tmp_path / "nowhere",
            )

    def test_mixed_contract_judges_normative_and_empirical_together(self, tmp_path: Path) -> None:
        self._bind()
        contract = self.CONTRACT.replace(
            'criteria:\n  - name: keeps-up\n    contains: "ok"',
            'criteria:\n  - name: stated-bar\n    threshold: 0.5\n    contains: "ok"\n'
            '  - name: keeps-up\n    contains: "ok"',
        )
        path = write_contract(tmp_path, contract)
        run(path, mode="measure", samples=200, baseline_dir=tmp_path / "baselines", emit=False)
        result = run(path, mode="test", baseline_dir=tmp_path / "baselines", emit=False)
        assert result.composite is Verdict.PASS
        origins = {r.name: r.criterion.provenance.origin for r in result.criterion_results}
        assert origins["stated-bar"] == "unspecified"
        assert origins["keeps-up"] == "empirical"


class TestPerInputAttribution:
    def test_expected_failure_reason_names_its_input(self, tmp_path: Path) -> None:
        @binding("echo2")
        def echo(value: str) -> str:
            return value

        contract = """
format: mavai-contract/1
contract: t
service: echo2
intent: smoke
criteria:
  - name: echoes
    threshold: 0.9
    matches: "."
inputs:
  - input: "bad"
    expected: { contains: "impossible" }
"""
        result = run(write_contract(tmp_path, contract), samples=2, emit=False)
        reasons = list(result.criterion_results[0].tally.failure_reasons)
        assert any("for input 'bad':" in reason for reason in reasons)
