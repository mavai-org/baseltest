"""Provider adapters: protocol shapes, credentials, schema pass-through, refusals."""

import io
import json
from typing import Any

import pytest

from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import (
    ENV_API_KEY,
    ENV_ENDPOINT,
    PROVIDERS,
    ProviderResponseError,
    build_invoker,
    resolve_provider,
)
from baseltest.declarative._services import LanguageModelParameters

PARAMETERS = LanguageModelParameters(system_prompt="You are helpful.", model="m1")
SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}}


@pytest.fixture()
def capture(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Stub urlopen; capture (url, headers, body); reply per provider shape."""
    calls: list[dict[str, Any]] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    replies = {
        "api.anthropic.com": {"content": [{"type": "text", "text": "claude says hi"}]},
        "localhost:11434": {"message": {"role": "assistant", "content": "ollama says hi"}},
    }

    def fake_urlopen(request: Any) -> FakeResponse:
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        reply: dict[str, Any] = {"choices": [{"message": {"content": "openai-style hi"}}]}
        for marker, shaped in replies.items():
            if marker in request.full_url:
                reply = shaped
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.delenv(ENV_ENDPOINT, raising=False)
    monkeypatch.setenv(ENV_API_KEY, "family-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


class TestRegistry:
    def test_out_of_the_box_vendors(self) -> None:
        assert set(PROVIDERS) == {"openai", "anthropic", "ollama", "mistral", "apertus", "litellm"}

    def test_unknown_provider_lists_supported(self) -> None:
        with pytest.raises(ContractConfigurationError, match="apertus"):
            resolve_provider("closedai")

    def test_omitted_provider_is_generic(self) -> None:
        assert resolve_provider(None).name == "openai-compatible"


class TestRequestShapes:
    def test_openai(self, capture: list[dict[str, Any]]) -> None:
        invoke = build_invoker(resolve_provider("openai"), PARAMETERS)
        assert invoke("hello") == "openai-style hi"
        call = capture[0]
        assert call["url"] == "https://api.openai.com/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer family-key"
        assert call["body"]["messages"][0]["role"] == "system"

    def test_anthropic_protocol_shape(self, capture: list[dict[str, Any]]) -> None:
        invoke = build_invoker(resolve_provider("anthropic"), PARAMETERS)
        assert invoke("hello") == "claude says hi"
        call = capture[0]
        assert call["url"] == "https://api.anthropic.com/v1/messages"
        assert call["headers"]["X-api-key"] == "family-key"
        assert call["headers"]["Anthropic-version"]
        body = call["body"]
        assert body["system"] == "You are helpful."
        assert body["max_tokens"] == 4096
        assert body["messages"] == [{"role": "user", "content": "hello"}]

    def test_ollama_local_no_credential(
        self, capture: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        invoke = build_invoker(resolve_provider("ollama"), PARAMETERS)
        assert invoke("hello") == "ollama says hi"
        call = capture[0]
        assert "localhost:11434" in call["url"]
        assert call["body"]["stream"] is False
        assert "Authorization" not in call["headers"]

    def test_apertus_defaults_to_public_ai(self, capture: list[dict[str, Any]]) -> None:
        invoke = build_invoker(resolve_provider("apertus"), PARAMETERS)
        invoke("grüezi")
        assert capture[0]["url"] == "https://api.publicai.co/v1/chat/completions"

    def test_endpoint_environment_override(
        self, capture: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_ENDPOINT, "https://my-vllm.internal/v1/chat/completions")
        invoke = build_invoker(resolve_provider("openai"), PARAMETERS)
        invoke("hello")
        assert capture[0]["url"] == "https://my-vllm.internal/v1/chat/completions"


class TestCredentials:
    def test_vendor_conventional_fallback(
        self, capture: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "vendor-key")
        invoke = build_invoker(resolve_provider("mistral"), PARAMETERS)
        invoke("hello")
        assert capture[0]["headers"]["Authorization"] == "Bearer vendor-key"

    def test_missing_credential_is_a_constructive_refusal(
        self, capture: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ContractConfigurationError, match="OPENAI_API_KEY"):
            build_invoker(resolve_provider("openai"), PARAMETERS)


class TestResponseSchema:
    def test_openai_style_pass_through(self, capture: list[dict[str, Any]]) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", response_schema=SCHEMA)
        invoke = build_invoker(resolve_provider("openai"), parameters)
        invoke("hello")
        response_format = capture[0]["body"]["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["schema"] == SCHEMA

    def test_ollama_format_pass_through(self, capture: list[dict[str, Any]]) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", response_schema=SCHEMA)
        invoke = build_invoker(resolve_provider("ollama"), parameters)
        invoke("hello")
        assert capture[0]["body"]["format"] == SCHEMA

    def test_anthropic_structured_output_pass_through(self, capture: list[dict[str, Any]]) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", response_schema=SCHEMA)
        invoke = build_invoker(resolve_provider("anthropic"), parameters)
        invoke("hello")
        output_config = capture[0]["body"]["output_config"]
        assert output_config["format"]["type"] == "json_schema"
        assert output_config["format"]["schema"] == SCHEMA

    def test_unsupporting_provider_refused_at_load_never_degraded(
        self, capture: list[dict[str, Any]]
    ) -> None:
        # apertus's hosted endpoint asserts no structured-output support
        parameters = LanguageModelParameters(system_prompt="s", model="m1", response_schema=SCHEMA)
        with pytest.raises(ContractConfigurationError, match="cannot be honoured"):
            build_invoker(resolve_provider("apertus"), parameters)
        assert capture == []


class TestClientFactors:
    def test_top_p_passes_through_like_temperature(self, capture: list[dict[str, Any]]) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", top_p=0.9)
        build_invoker(resolve_provider("openai"), parameters)("hello")
        build_invoker(resolve_provider("anthropic"), parameters)("hello")
        build_invoker(resolve_provider("ollama"), parameters)("hello")
        assert capture[0]["body"]["top_p"] == 0.9
        assert capture[1]["body"]["top_p"] == 0.9
        assert capture[2]["body"]["options"]["top_p"] == 0.9

    def test_anthropic_prompt_caching_marks_the_system_block(
        self, capture: list[dict[str, Any]]
    ) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", prompt_caching=True)
        build_invoker(resolve_provider("anthropic"), parameters)("hello")
        assert capture[0]["body"]["system"] == [
            {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
        ]

    def test_anthropic_adaptive_thinking_passes_through(
        self, capture: list[dict[str, Any]]
    ) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", thinking="adaptive")
        build_invoker(resolve_provider("anthropic"), parameters)("hello")
        assert capture[0]["body"]["thinking"] == {"type": "adaptive"}

    def test_declared_off_values_are_honoured_everywhere(
        self, capture: list[dict[str, Any]]
    ) -> None:
        # `thinking: none` and `prompt-caching: false` state today's behaviour
        # explicitly — every provider honours them by sending nothing.
        parameters = LanguageModelParameters(
            system_prompt="s", model="m1", thinking="none", prompt_caching=False
        )
        build_invoker(resolve_provider("openai"), parameters)("hello")
        build_invoker(resolve_provider("anthropic"), parameters)("hello")
        assert "thinking" not in capture[0]["body"] and "thinking" not in capture[1]["body"]
        assert capture[1]["body"]["system"] == "s"

    def test_prompt_caching_on_an_unsupporting_provider_is_refused(
        self, capture: list[dict[str, Any]]
    ) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", prompt_caching=True)
        with pytest.raises(ContractConfigurationError, match="cannot be honoured"):
            build_invoker(resolve_provider("openai"), parameters)
        assert capture == []

    def test_thinking_on_an_unsupporting_provider_is_refused(
        self, capture: list[dict[str, Any]]
    ) -> None:
        parameters = LanguageModelParameters(system_prompt="s", model="m1", thinking="adaptive")
        with pytest.raises(ContractConfigurationError, match="cannot be honoured"):
            build_invoker(resolve_provider("ollama"), parameters)
        assert capture == []

    def test_anthropic_thinking_with_sampling_parameters_is_refused(
        self, capture: list[dict[str, Any]]
    ) -> None:
        with_temperature = LanguageModelParameters(
            system_prompt="s", model="m1", thinking="adaptive", temperature=0.7
        )
        with_top_p = LanguageModelParameters(
            system_prompt="s", model="m1", thinking="adaptive", top_p=0.9
        )
        for parameters in (with_temperature, with_top_p):
            with pytest.raises(ContractConfigurationError, match="constrains sampling"):
                build_invoker(resolve_provider("anthropic"), parameters)
        assert capture == []


class TestErrorResponses:
    def test_http_error_is_a_diagnosable_defect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An error response aborts the run (a defect, never a sample) — and
        # the abort carries the provider's own explanation, not a bare 400.
        import urllib.error

        def failing_urlopen(request: Any) -> Any:
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                None,  # type: ignore[arg-type]
                io.BytesIO(b'{"error": {"message": "schema: additionalProperties required"}}'),
            )

        monkeypatch.setenv(ENV_API_KEY, "family-key")
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
        invoke = build_invoker(resolve_provider("anthropic"), PARAMETERS)
        with pytest.raises(ProviderResponseError) as defect:
            invoke("hello")
        message = str(defect.value)
        assert "'anthropic'" in message and "400" in message
        assert "additionalProperties required" in message  # the provider's words survive
        assert "defect" in message
