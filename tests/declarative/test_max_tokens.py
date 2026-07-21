"""The output ceiling is a declared, per-provider, fingerprinted parameter.

`max-tokens:` is admitted as a language-model configuration key: validated at
load time, translated to each provider's own wire parameter, recorded in
identity so a changed ceiling drifts a baseline, and resolved to a default when
unstated so no service inherits a silent ceiling.
"""

import pytest

from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import PROVIDERS
from baseltest.declarative._services import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS_CEILING,
    LanguageModelParameters,
    _validate_configuration,
    resolved_provenance,
)

_BASE = {"system-prompt": "You are a service.", "model": "a-model"}


def _params(**overrides: object) -> LanguageModelParameters:
    return LanguageModelParameters(system_prompt="You are a service.", **overrides)  # type: ignore[arg-type]


# ── per-adapter translation (one declared key, each provider's own parameter) ──


def test_anthropic_and_openai_compatible_use_max_tokens() -> None:
    params = _params(max_tokens=12000)
    for name in ("anthropic", "mistral", "apertus"):
        body = PROVIDERS[name].body(params, "a-model", "hello")
        assert body["max_tokens"] == 12000, name


def test_openai_uses_max_completion_tokens() -> None:
    body = PROVIDERS["openai"].body(_params(max_tokens=12000), "a-model", "hello")
    assert body["max_completion_tokens"] == 12000
    assert "max_tokens" not in body  # the old key is rejected by reasoning models


def test_ollama_uses_num_predict_under_options() -> None:
    body = PROVIDERS["ollama"].body(_params(max_tokens=12000), "a-model", "hello")
    assert body["options"]["num_predict"] == 12000


def test_every_adapter_carries_the_ceiling() -> None:
    params = _params(max_tokens=8000)
    for name, provider in PROVIDERS.items():
        body = provider.body(params, "a-model", "hello")
        emitted = body.get("max_tokens") or body.get("max_completion_tokens")
        if emitted is None:
            emitted = body.get("options", {}).get("num_predict")
        assert emitted == 8000, f"{name} did not translate the ceiling"


# ── load-time validation (what `basel check` runs for zero samples) ───────────


def test_stated_ceiling_loads() -> None:
    params = _validate_configuration("svc", {**_BASE, "max-tokens": 16000}, "the configuration")
    assert params.max_tokens == 16000


def test_unstated_ceiling_resolves_to_the_default() -> None:
    params = _validate_configuration("svc", dict(_BASE), "the configuration")
    assert params.max_tokens == DEFAULT_MAX_TOKENS


@pytest.mark.parametrize("bad", ["16000", 1.5, True, 0, -1, MAX_TOKENS_CEILING + 1])
def test_out_of_range_or_wrong_type_is_refused(bad: object) -> None:
    with pytest.raises(ContractConfigurationError):
        _validate_configuration("svc", {**_BASE, "max-tokens": bad}, "the configuration")


def test_ceiling_too_small_for_adaptive_thinking_is_refused() -> None:
    with pytest.raises(ContractConfigurationError, match="thinking"):
        _validate_configuration(
            "svc", {**_BASE, "thinking": "adaptive", "max-tokens": 1024}, "the configuration"
        )


def test_adaptive_thinking_with_room_loads() -> None:
    params = _validate_configuration(
        "svc", {**_BASE, "thinking": "adaptive", "max-tokens": 16000}, "the configuration"
    )
    assert params.max_tokens == 16000


# ── fingerprinted identity (a changed ceiling drifts a baseline) ──────────────


def test_ceiling_is_in_identity_and_drives_drift() -> None:
    at_4096 = resolved_provenance(_params(max_tokens=4096))
    at_8000 = resolved_provenance(_params(max_tokens=8000))
    assert at_4096["maxTokens"] == "4096"
    assert at_8000["maxTokens"] == "8000"
    assert at_4096 != at_8000  # the sole difference; the identities diverge


def test_unstated_ceiling_is_still_recorded_in_identity() -> None:
    assert resolved_provenance(_params())["maxTokens"] == str(DEFAULT_MAX_TOKENS)
