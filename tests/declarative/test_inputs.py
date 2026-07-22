"""Typed inputs and the inputs ↔ binding-signature join."""

import hashlib
import json
from pathlib import Path

import pytest

from baseltest.declarative import Bindings, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.engine import Verdict, inputs_fingerprint


def write_contract(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


FORECAST_CONTRACT = """
format: mavai-contract/1
contract: forecast-is-complete
service: forecast
criteria:
  - threshold: 0.5
    matches: "days"
inputs:
  - ["Basel", 3, true]
  - ["Oslo", 1, false]
"""


def register_forecast(bindings: Bindings) -> None:
    @bindings.binding("forecast")
    def forecast(city: str, days: int, metric: bool) -> str:
        unit = "C" if metric else "F"
        return f"{city}: {days} days of sun, 20{unit}"


class TestTupleInputs:
    def test_list_inputs_splat_as_positional_arguments(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_forecast(bindings)
        result = run(write_contract(tmp_path, FORECAST_CONTRACT), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS

    def test_scalar_non_string_input_reaches_a_single_parameter_binding(
        self, tmp_path: Path
    ) -> None:
        bindings = Bindings()

        @bindings.binding("doubler")
        def doubler(count: int) -> str:
            return str(count * 2)

        contract = """
format: mavai-contract/1
contract: doubles
service: doubler
criteria:
  - threshold: 0.5
    equals: "14"
inputs: [7]
"""
        result = run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS

    def test_per_input_expectations_dispatch_on_tuple_inputs(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_forecast(bindings)
        contract = """
format: mavai-contract/1
contract: forecast-is-complete
service: forecast
criteria:
  - threshold: 0.5
    matches: "days"
inputs:
  - input: ["Basel", 3, true]
    expected: { contains: "20C" }
  - input: ["Oslo", 1, false]
    expected: { contains: "20F" }
"""
        result = run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS


class TestInputJoinRefusals:
    def test_arity_mismatch_names_the_input_and_carries_the_signature(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_forecast(bindings)
        contract = FORECAST_CONTRACT.replace('- ["Oslo", 1, false]', '- ["Oslo", 1]')
        with pytest.raises(ContractConfigurationError) as refusal:
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        message = str(refusal.value)
        assert "input 2" in message
        assert "2 values" in message
        assert "forecast(city: str, days: int, metric: bool)" in message

    def test_annotated_type_mismatch_names_the_parameter(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_forecast(bindings)
        contract = FORECAST_CONTRACT.replace('- ["Oslo", 1, false]', '- ["Oslo", "one", false]')
        with pytest.raises(ContractConfigurationError, match="'days' expects int, got str"):
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)

    def test_refusal_fires_before_any_invocation(self, tmp_path: Path) -> None:
        calls: list[str] = []
        bindings = Bindings()

        @bindings.binding("counting")
        def counting(city: str, days: int) -> str:
            calls.append(city)
            return city

        contract = FORECAST_CONTRACT.replace("service: forecast", "service: counting")
        with pytest.raises(ContractConfigurationError):
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert calls == []

    def test_nested_input_structures_are_refused_by_the_parser(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_forecast(bindings)
        contract = FORECAST_CONTRACT.replace('- ["Oslo", 1, false]', '- ["Oslo", [1, 2], false]')
        with pytest.raises(ContractConfigurationError, match="flat list of scalars"):
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)


class TestInputsFingerprint:
    def test_all_string_inputs_keep_the_historical_canonical_form(self) -> None:
        inputs = ("Bob", "Alice")
        historical = hashlib.sha256(
            json.dumps(sorted(inputs), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert inputs_fingerprint(inputs) == historical

    def test_structured_inputs_fingerprint_is_order_insensitive(self) -> None:
        one = inputs_fingerprint((("Basel", 3, True), 7, "plain"))
        two = inputs_fingerprint(("plain", 7, ("Basel", 3, True)))
        assert one == two

    def test_structured_and_string_corpora_do_not_collide(self) -> None:
        assert inputs_fingerprint(("7",)) != inputs_fingerprint((7,))
