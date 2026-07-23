"""Author-declared provider capabilities: the `capabilities:` allowance.

A gateway adapter (litellm) speaks an OpenAI-compatible protocol but fronts
many upstream models behind mutable aliases, so it cannot infer from the
protocol which capabilities the aliased upstream honours. The contract author
declares them; the adapter encodes them. Declaring widens what measure/test and
explore will send and joins the drift-checked identity; declaring a capability
the adapter cannot encode is refused at load, with zero samples.
"""

import pytest

from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import PROVIDERS, build_invoker, resolve_provider
from baseltest.declarative._services import (
    LanguageModelParameters,
    _validate_configuration,
    resolved_provenance,
)

_BASE = {"system-prompt": "You are a service.", "model": "a-model"}


def _validate(**config: object) -> LanguageModelParameters:
    return _validate_configuration("svc", {**_BASE, **config}, "the configuration")


def _params(**overrides: object) -> LanguageModelParameters:
    return LanguageModelParameters(system_prompt="You are a service.", **overrides)  # type: ignore[arg-type]


# ── load-time validation (zero samples: what `basel check` runs) ──────────────


class TestVocabulary:
    def test_unknown_capability_is_refused_naming_the_supported_set(self) -> None:
        with pytest.raises(ContractConfigurationError, match="unknown capability"):
            _validate(provider="litellm", capabilities=["telepathy"])

    def test_capabilities_must_be_a_list_of_names(self) -> None:
        with pytest.raises(ContractConfigurationError, match="list of capability"):
            _validate(provider="litellm", capabilities="prompt-caching")


class TestEncodabilityGate:
    def test_generic_cannot_encode_caching_or_thinking(self) -> None:
        # The generic OpenAI-compatible body has no wire form for either, so a
        # flag on GENERIC would be permission to send an unencodable key.
        for capability in ("prompt-caching", "thinking"):
            with pytest.raises(ContractConfigurationError, match="cannot encode"):
                _validate(capabilities=[capability])  # provider omitted → GENERIC

    def test_generic_response_schema_declaration_is_a_redundant_no_op(self) -> None:
        # response-schema is optimistically on for GENERIC and IS encoded, so
        # declaring it is accepted, not an error.
        params = _validate(capabilities=["response-schema"])
        assert params.capabilities == frozenset({"response-schema"})

    def test_apertus_refuses_a_response_schema_override(self) -> None:
        # apertus withholds structured output on its hosted endpoint by design;
        # the author may not turn it on by declaration.
        with pytest.raises(ContractConfigurationError, match="cannot encode"):
            _validate(provider="apertus", capabilities=["response-schema"])

    def test_litellm_accepts_the_full_vocabulary(self) -> None:
        params = _validate(
            provider="litellm",
            capabilities=["response-schema", "prompt-caching", "thinking"],
        )
        assert params.capabilities == frozenset({"response-schema", "prompt-caching", "thinking"})


class TestWidensMeasureTest:
    def test_undeclared_caching_on_litellm_is_refused(self) -> None:
        # Undeclared, prompt_caching on litellm behaves exactly as today: its
        # static support is False, so measure/test refuses at load.
        with pytest.raises(ContractConfigurationError, match="cannot be honoured"):
            build_invoker(
                resolve_provider("litellm"),
                _params(prompt_caching=True),
            )

    def test_declared_caching_on_litellm_loads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Declared, the same configuration builds its invoker without refusal.
        monkeypatch.setenv("MAVAI_LLM_ENDPOINT", "https://litellm.example/v1/chat/completions")
        monkeypatch.setenv("MAVAI_LLM_API_KEY", "sk-test")
        invoke = build_invoker(
            resolve_provider("litellm"),
            _params(
                model="a-model", prompt_caching=True, capabilities=frozenset({"prompt-caching"})
            ),
        )
        assert callable(invoke)


# ── wire-form (the request body actually carries the encoding) ────────────────


class TestWireForm:
    def test_declared_caching_marks_the_system_message(self) -> None:
        params = _params(prompt_caching=True, capabilities=frozenset({"prompt-caching"}))
        body = PROVIDERS["litellm"].body(params, "a-model", "hello")
        system_message = body["messages"][0]
        assert system_message["role"] == "system"
        assert system_message["content"] == [
            {
                "type": "text",
                "text": "You are a service.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_declared_thinking_carries_a_reasoning_parameter(self) -> None:
        params = _params(
            thinking="adaptive", max_tokens=16000, capabilities=frozenset({"thinking"})
        )
        body = PROVIDERS["litellm"].body(params, "a-model", "hello")
        assert "reasoning_effort" in body

    def test_declared_schema_uses_response_format(self) -> None:
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        params = _params(response_schema=schema, capabilities=frozenset({"response-schema"}))
        body = PROVIDERS["litellm"].body(params, "a-model", "hello")
        assert body["response_format"]["json_schema"]["schema"] == schema

    def test_without_caching_the_system_message_stays_a_plain_string(self) -> None:
        body = PROVIDERS["litellm"].body(_params(), "a-model", "hello")
        assert body["messages"][0]["content"] == "You are a service."


# ── drift-checked identity (widening the allowance drifts a baseline) ─────────


class TestIdentity:
    def test_capabilities_join_identity(self) -> None:
        without = resolved_provenance(_params())
        widened = resolved_provenance(_params(capabilities=frozenset({"prompt-caching"})))
        assert "capabilities" not in without
        assert widened["capabilities"] == "prompt-caching"
        assert without != widened  # the sole difference; the identities diverge

    def test_capability_set_is_recorded_sorted_for_determinism(self) -> None:
        entries = resolved_provenance(
            _params(capabilities=frozenset({"thinking", "prompt-caching"}))
        )
        assert entries["capabilities"] == "prompt-caching,thinking"
