"""Service definitions: parsing, addressing, collision, and the language-model type."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import binding, run
from baseltest.declarative._errors import TaskConfigurationError
from baseltest.declarative._registry import clear_registries
from baseltest.declarative._services import (
    ENV_ENDPOINT,
    ENV_MODEL,
    parse_services,
)
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

TASK = """
format: mavai-task/1
task: greeting-is-polite
service: greeter
samples: 100
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


def write_files(tmp_path: Path, task: str = TASK, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    task_path = tmp_path / "task.yaml"
    task_path.write_text(task, encoding="utf-8")
    return task_path


class TestParsing:
    def test_system_prompt_required(self) -> None:
        text = SERVICES.replace(
            '      system-prompt: "You are a polite greeter."', "      model: some-model"
        )
        with pytest.raises(TaskConfigurationError, match="system-prompt"):
            parse_services(text)

    def test_parameters_outside_configuration_refused_with_uniformity_rule(self) -> None:
        text = SERVICES.replace(
            "  greeter:\n    type: language-model\n",
            "  greeter:\n    type: language-model\n    temperature: 0.3\n",
        )
        with pytest.raises(TaskConfigurationError, match="inside the `configuration:` block"):
            parse_services(text)

    def test_variations_reserved(self) -> None:
        text = SERVICES + "    variations:\n      temperature: [0.0, 0.7]\n"
        with pytest.raises(TaskConfigurationError, match="reserved"):
            parse_services(text)

    def test_unknown_type_refused(self) -> None:
        with pytest.raises(TaskConfigurationError, match="language-model"):
            parse_services(SERVICES.replace("type: language-model", "type: robot", 1))

    def test_unknown_key_refused(self) -> None:
        with pytest.raises(TaskConfigurationError, match="api-key"):
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
        task = TASK.replace("service: greeter", "service: support-agent")
        result = run(write_files(tmp_path, task=task), emit=False)
        assert result.composite is Verdict.PASS
        payload = llm_environment[0]
        assert payload["model"] == "small-model"
        assert payload["temperature"] == 0.7
        assert "max_tokens" not in payload

    def test_missing_endpoint_is_a_constructive_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        with pytest.raises(TaskConfigurationError, match=ENV_ENDPOINT):
            run(write_files(tmp_path), emit=False)


class TestResolutionRules:
    def test_collision_between_code_and_definition_fails(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        @binding("greeter")
        def greet(value: str) -> str:
            return f"hello {value}"

        with pytest.raises(TaskConfigurationError, match="one name, one owner"):
            run(write_files(tmp_path), emit=False)


class TestProvenance:
    def test_measure_baseline_carries_resolved_service_parameters(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        task = TASK.replace("service: greeter", "service: support-agent")
        task += "kind: measure\n"
        run(write_files(tmp_path, task=task), baseline_dir=tmp_path / "b", emit=False)
        content = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")
        assert '"serviceType": "language-model"' in content
        assert '"systemPrompt": "You are a support agent."' in content
        assert '"model": "small-model"' in content
        assert '"temperature": "0.7"' in content
