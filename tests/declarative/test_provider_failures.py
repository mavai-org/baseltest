"""Provider failure classification: delivery failures are samples; rejections are defects."""

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from baseltest.contract import ServiceDeliveryError
from baseltest.declarative._providers import (
    ProviderResponseError,
    build_invoker,
    resolve_provider,
)
from baseltest.declarative._services import LanguageModelParameters


@pytest.fixture()
def invoker(monkeypatch: Any):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    parameters = LanguageModelParameters(
        system_prompt="terse", provider="openai", model="gpt-4o-mini", temperature=0.0
    )
    return build_invoker(resolve_provider("openai"), parameters)


def _raise(monkeypatch: Any, error: Exception) -> None:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.openai.com",
        status,
        "err",
        hdrs=None,
        fp=io.BytesIO(body),  # type: ignore[arg-type]
    )


class TestClassification:
    def test_unreachable_is_a_failed_delivery(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, urllib.error.URLError("nodename nor servname provided"))
        with pytest.raises(ServiceDeliveryError, match="service unreachable at"):
            invoker("hello")

    def test_server_error_is_a_failed_delivery(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, _http_error(503, b"overloaded"))
        with pytest.raises(ServiceDeliveryError, match="HTTP 503"):
            invoker("hello")

    def test_client_error_is_a_rejection_defect(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, _http_error(401, b"bad key"))
        with pytest.raises(ProviderResponseError, match="HTTP 401"):
            invoker("hello")


def _reply(monkeypatch: Any, body: dict[str, Any]) -> None:
    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


@pytest.fixture()
def anthropic_thinking_invoker(monkeypatch: Any):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    parameters = LanguageModelParameters(
        system_prompt="terse", provider="anthropic", model="m1", thinking="adaptive"
    )
    return build_invoker(resolve_provider("anthropic"), parameters)


class TestDeliveredBodyShapes:
    """A delivered 2xx body is judged, never crashed on: odd shapes are failed samples."""

    def test_thinking_first_text_second_extracts(
        self, anthropic_thinking_invoker: Any, monkeypatch: Any
    ) -> None:
        _reply(
            monkeypatch,
            {
                "content": [
                    {"type": "thinking", "thinking": "step by step...", "signature": "s"},
                    {"type": "text", "text": "the answer"},
                ],
                "stop_reason": "end_turn",
            },
        )
        assert anthropic_thinking_invoker("hello") == "the answer"

    def test_redacted_thinking_blocks_are_tolerated_anywhere(
        self, anthropic_thinking_invoker: Any, monkeypatch: Any
    ) -> None:
        _reply(
            monkeypatch,
            {
                "content": [
                    {"type": "redacted_thinking", "data": "opaque"},
                    {"type": "thinking", "thinking": "...", "signature": "s"},
                    {"type": "text", "text": "the answer"},
                ],
                "stop_reason": "end_turn",
            },
        )
        assert anthropic_thinking_invoker("hello") == "the answer"

    def test_no_text_block_is_a_failed_delivery_naming_the_cause(
        self, anthropic_thinking_invoker: Any, monkeypatch: Any
    ) -> None:
        # e.g. max-token truncation inside thinking: billed, delivered, no
        # assistant text — a counted failed sample, never an engine crash.
        _reply(
            monkeypatch,
            {
                "content": [{"type": "thinking", "thinking": "...", "signature": "s"}],
                "stop_reason": "max_tokens",
            },
        )
        with pytest.raises(ServiceDeliveryError, match="no text content block") as failure:
            anthropic_thinking_invoker("hello")
        assert "thinking" in str(failure.value)
        assert "max_tokens" in str(failure.value)

    def test_non_thinking_anthropic_response_unchanged(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        parameters = LanguageModelParameters(
            system_prompt="terse", provider="anthropic", model="m1"
        )
        invoker = build_invoker(resolve_provider("anthropic"), parameters)
        _reply(monkeypatch, {"content": [{"type": "text", "text": "plain"}]})
        assert invoker("hello") == "plain"

    def test_body_not_matching_the_vendor_shape_is_a_failed_delivery(
        self, invoker: Any, monkeypatch: Any
    ) -> None:
        _reply(monkeypatch, {"unexpected": "shape"})
        with pytest.raises(ServiceDeliveryError, match="not matching the openai shape"):
            invoker("hello")

    def test_null_content_is_a_failed_delivery(self, invoker: Any, monkeypatch: Any) -> None:
        _reply(monkeypatch, {"choices": [{"message": {"content": None}}]})
        with pytest.raises(ServiceDeliveryError, match="no text content"):
            invoker("hello")
