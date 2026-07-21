"""Service definitions: parsing, addressing, collision, and the language-model type."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import binding, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL
from baseltest.declarative._registry import clear_registries
from baseltest.declarative._services import parse_services
from baseltest.statistics.verdict import Verdict

SERVICES = """
format: mavai-services/1
services:
  greeter:
    type: language-model
    configuration:
      system-prompt: "You are a polite greeter."
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.7
"""

CONTRACT = """
format: mavai-contract/1
contract: greeting-is-polite
service: greeter
inputs: ["Alice", "Bob"]
criteria:
  - threshold: 0.5
    contains: "hello"
"""


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


@pytest.fixture()
def llm_environment(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A stubbed OpenAI-compatible endpoint capturing request payloads."""
    captured: list[dict[str, Any]] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request: Any) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        reply = {"choices": [{"message": {"content": f"hello from {payload['model']}"}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


def write_files(tmp_path: Path, contract: str = CONTRACT, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(contract, encoding="utf-8")
    return contract_path


class TestParsing:
    def test_system_prompt_required(self) -> None:
        text = SERVICES.replace(
            '      system-prompt: "You are a polite greeter."', "      model: some-model"
        )
        with pytest.raises(ContractConfigurationError, match="system-prompt"):
            parse_services(text)

    def test_parameters_outside_configuration_refused_with_uniformity_rule(self) -> None:
        text = SERVICES.replace(
            "  greeter:\n    type: language-model\n",
            "  greeter:\n    type: language-model\n    temperature: 0.3\n",
        )
        with pytest.raises(ContractConfigurationError, match="inside the `configuration:` block"):
            parse_services(text)

    def test_withdrawn_variations_key_fails_the_ordinary_unknown_key_check(self) -> None:
        # The pre-release rename ruling: no rename pointer, just an unknown key.
        text = SERVICES + "    variations:\n      temperature: [0.0, 0.7]\n"
        with pytest.raises(ContractConfigurationError, match="unknown key `variations:`"):
            parse_services(text)

    def test_thinking_value_outside_the_vocabulary_refused(self) -> None:
        text = SERVICES.replace("temperature: 0.7", "thinking: deep")
        with pytest.raises(ContractConfigurationError, match="adaptive, none"):
            parse_services(text)

    def test_top_p_outside_the_unit_interval_refused(self) -> None:
        for bad in ("0", "1.2", "true", '"high"'):
            text = SERVICES.replace("temperature: 0.7", f"top-p: {bad}")
            with pytest.raises(ContractConfigurationError, match="top-p"):
                parse_services(text)

    def test_prompt_caching_must_be_a_boolean(self) -> None:
        text = SERVICES.replace("temperature: 0.7", "prompt-caching: ephemeral")
        with pytest.raises(ContractConfigurationError, match="prompt-caching"):
            parse_services(text)

    def test_unknown_type_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="language-model"):
            parse_services(SERVICES.replace("type: language-model", "type: robot", 1))

    def test_unknown_key_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="api-key"):
            parse_services(SERVICES + "    api-key: leak\n")


class TestZeroCodePath:
    def test_two_files_to_verdict_with_env_default_model(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        result = run(write_files(tmp_path), emit=False)
        assert result.composite is Verdict.PASS
        assert llm_environment[0]["model"] == "env-default-model"
        assert llm_environment[0]["messages"][0] == {
            "role": "system",
            "content": "You are a polite greeter.",
        }

    def test_full_configuration_reaches_the_endpoint(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        contract = CONTRACT.replace("service: greeter", "service: support-agent")
        result = run(write_files(tmp_path, contract=contract), emit=False)
        assert result.composite is Verdict.PASS
        payload = llm_environment[0]
        assert payload["model"] == "small-model"
        assert payload["temperature"] == 0.7
        # The output ceiling is always sent, resolved to its default when
        # unstated — no provider inherits a silent, unrecorded ceiling.
        assert payload["max_tokens"] == 4096

    def test_missing_endpoint_is_a_constructive_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        with pytest.raises(ContractConfigurationError, match=ENV_ENDPOINT):
            run(write_files(tmp_path), emit=False)


class TestResolutionRules:
    def test_service_names_and_type_names_are_separate_namespaces(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        # A registered type sharing a service definition's name is not a
        # collision: a contract's `service:` reference resolves against
        # service definitions first.
        @binding("greeter")
        def greet(value: str) -> str:
            return f"hello {value}"

        result = run(write_files(tmp_path), emit=False)
        assert llm_environment  # the definition won: the model was invoked
        assert result.composite is Verdict.PASS

    def test_registering_a_builtin_type_name_is_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="built-in service type"):

            @binding("language-model")
            def invoke(value: str) -> str:
                return value

    def test_configurable_type_is_not_directly_addressable(self, tmp_path: Path) -> None:
        from baseltest.declarative import binding_factory

        @binding_factory("teller")
        def teller(mood: str = "cheerful"):  # type: ignore[no-untyped-def]
            return lambda value: f"{mood} {value}"

        contract = tmp_path / "contract.yaml"
        contract.write_text(CONTRACT.replace("service: greeter", "service: teller"))
        with pytest.raises(ContractConfigurationError, match="mavai-services.yaml"):
            run(contract, emit=False)


class TestProvenance:
    def test_measure_baseline_carries_resolved_service_parameters(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        contract = CONTRACT.replace("service: greeter", "service: support-agent")
        run(
            write_files(tmp_path, contract=contract),
            mode="measure",
            samples=20,
            baseline_dir=tmp_path / "b",
            emit=False,
        )
        content = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")
        assert '"serviceType": "language-model"' in content
        assert '"systemPrompt": "You are a support agent."' in content
        assert '"model": "small-model"' in content
        assert '"temperature": "0.7"' in content

    def test_client_factors_join_provenance_and_drift_check(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        services = SERVICES.replace("temperature: 0.7", "top-p: 0.9")
        empirical_only = CONTRACT.replace("  - threshold: 0.5\n", "  - ")
        contract = CONTRACT.replace("service: greeter", "service: support-agent")
        empirical = empirical_only.replace("service: greeter", "service: support-agent")
        run(
            write_files(tmp_path, contract=contract, services=services),
            mode="measure",
            samples=20,
            baseline_dir=tmp_path / "b",
            emit=False,
        )
        content = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")
        assert '"topP": "0.9"' in content
        assert llm_environment[0]["top_p"] == 0.9
        # A baseline measured under one top-p refuses a test under another,
        # naming the drifted key — configuration keys join identity natively.
        write_files(
            tmp_path,
            contract=empirical,
            services=services.replace("top-p: 0.9", "top-p: 0.95"),
        )
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(empirical, encoding="utf-8")
        with pytest.raises(ContractConfigurationError) as refusal:
            run(contract_path, mode="test", baseline_dir=tmp_path / "b", emit=False)
        assert "topP" in str(refusal.value)
