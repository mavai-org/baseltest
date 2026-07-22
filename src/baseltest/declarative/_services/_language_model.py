"""The built-in ``language-model`` service type: validation, provenance, invoker.

The first entry on the generic service-type seam: it validates a resolved
configuration mapping, projects a configuration into provenance and resolved
values, builds the per-sample invoker via the provider adapters, and
announces (never silently drops) per-provider capability degradation when an
explore grid spans providers.
"""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as _replace
from typing import Any

from .._providers import ENV_MODEL, build_invoker, resolve_provider
from .._types import ServiceTypeContract
from ._model import _fail

_CONFIGURATION_KEYS = {
    "system-prompt",
    "provider",
    "model",
    "temperature",
    "top-p",
    "thinking",
    "prompt-caching",
    "response-schema",
    "max-tokens",
}
# Canonical parameter order: stems and factor blocks list swept covariates
# in this order so artefacts from one grid stay field-for-field diffable.
_PARAMETER_ORDER = (
    "system-prompt",
    "provider",
    "model",
    "temperature",
    "top-p",
    "thinking",
    "prompt-caching",
    "response-schema",
    "max-tokens",
)

_THINKING_VALUES = ("adaptive", "none")

# The output ceiling is a resolved-and-recorded parameter, never a hidden
# constant: unstated, it defaults to DEFAULT_MAX_TOKENS uniformly across
# providers (so a provider grid holds it constant), and the resolved value
# is fingerprinted into identity and the artefact. The upper bound is the
# largest ceiling the non-streaming adapters can carry without risking an
# HTTP timeout; larger ceilings await streaming support. Under
# `thinking: adaptive` the ceiling bounds thinking and answer together, so a
# value at or below the model's thinking floor leaves no room to answer.
DEFAULT_MAX_TOKENS = 4096
MAX_TOKENS_CEILING = 16000
_THINKING_MIN_MAX_TOKENS = 1024


@dataclass(frozen=True, slots=True)
class LanguageModelParameters:
    """One language-model service configuration: its complete covariate values."""

    system_prompt: str
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    thinking: str | None = None
    prompt_caching: bool | None = None
    response_schema: dict[str, Any] | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS


def _validate_configuration(
    name: str, configuration: dict[str, Any], where: str
) -> LanguageModelParameters:
    """Validate one resolved language-model configuration mapping."""
    for key in configuration:
        if key not in _CONFIGURATION_KEYS:
            raise _fail(f"service {name!r}: {where} has unknown key `{key}:`")
    system_prompt = configuration.get("system-prompt")
    if not isinstance(system_prompt, str) or not system_prompt:
        raise _fail(
            f"service {name!r}: `system-prompt:` is required in the {where} — "
            "a language-model service is a model given a job; without a system "
            "prompt there is a model, but no service to test"
        )
    provider_name = configuration.get("provider")
    if provider_name is not None:
        resolve_provider(str(provider_name))  # unknown names refused at load
    top_p = configuration.get("top-p")
    if top_p is not None and (
        isinstance(top_p, bool) or not isinstance(top_p, int | float) or not 0 < top_p <= 1
    ):
        raise _fail(
            f"service {name!r}: `top-p:` must be a number in (0, 1] — the "
            "cumulative probability mass nucleus sampling draws from"
        )
    thinking = configuration.get("thinking")
    if thinking is not None and thinking not in _THINKING_VALUES:
        values = ", ".join(_THINKING_VALUES)
        raise _fail(f"service {name!r}: `thinking:` must be one of: {values}")
    prompt_caching = configuration.get("prompt-caching")
    if prompt_caching is not None and not isinstance(prompt_caching, bool):
        raise _fail(f"service {name!r}: `prompt-caching:` must be a boolean")
    response_schema = configuration.get("response-schema")
    if response_schema is not None and not isinstance(response_schema, dict):
        raise _fail(
            f"service {name!r}: `response-schema:` must be a mapping (the JSON "
            "Schema the model is instructed to satisfy)"
        )
    max_tokens = configuration.get("max-tokens", DEFAULT_MAX_TOKENS)
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= MAX_TOKENS_CEILING
    ):
        raise _fail(
            f"service {name!r}: `max-tokens:` must be a whole number of output tokens "
            f"between 1 and {MAX_TOKENS_CEILING} — the ceiling on what the model may "
            "return; ceilings above this need streaming, which this reader does not yet "
            f"do. Unstated, it defaults to {DEFAULT_MAX_TOKENS} and is recorded as such."
        )
    if thinking == "adaptive" and max_tokens <= _THINKING_MIN_MAX_TOKENS:
        raise _fail(
            f"service {name!r}: `max-tokens: {max_tokens}` is too small for "
            "`thinking: adaptive` — the ceiling bounds thinking and answer together, so "
            f"at or below the model's {_THINKING_MIN_MAX_TOKENS}-token thinking floor the "
            "reasoning consumes the whole budget and the answer is truncated to nothing. "
            "Raise the ceiling or set `thinking: none`."
        )
    return LanguageModelParameters(
        system_prompt=system_prompt,
        provider=provider_name,
        model=configuration.get("model"),
        temperature=configuration.get("temperature"),
        top_p=top_p,
        thinking=thinking,
        prompt_caching=prompt_caching,
        response_schema=response_schema,
        max_tokens=max_tokens,
    )


def resolved_provenance(parameters: LanguageModelParameters) -> dict[str, str]:
    """The provenance entries a language-model-resolved run must carry."""
    entries = {
        "serviceType": "language-model",
        "provider": parameters.provider or "openai-compatible",
        "systemPrompt": parameters.system_prompt,
        "model": parameters.model or os.environ.get(ENV_MODEL, ""),
    }
    if parameters.temperature is not None:
        entries["temperature"] = str(parameters.temperature)
    if parameters.top_p is not None:
        entries["topP"] = str(parameters.top_p)
    if parameters.thinking is not None:
        entries["thinking"] = parameters.thinking
    if parameters.prompt_caching is not None:
        entries["promptCaching"] = "true" if parameters.prompt_caching else "false"
    if parameters.response_schema is not None:
        canonical = json.dumps(parameters.response_schema, sort_keys=True)
        entries["responseSchemaFingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # The output ceiling shapes the response as strongly as any sampling
    # parameter, so it is fingerprinted like one: a baseline taken under a
    # different ceiling is a different population, and a later test refuses
    # against it, naming the drifted key.
    entries["maxTokens"] = str(parameters.max_tokens)
    return entries


def _resolved_values(parameters: LanguageModelParameters) -> dict[str, Any]:
    return {
        "system-prompt": parameters.system_prompt,
        "provider": parameters.provider,
        "model": parameters.model or os.environ.get(ENV_MODEL) or None,
        "temperature": parameters.temperature,
        "top-p": parameters.top_p,
        "thinking": parameters.thinking,
        "prompt-caching": parameters.prompt_caching,
        "response-schema": parameters.response_schema,
        "max-tokens": parameters.max_tokens,
    }


def language_model_invoker(parameters: LanguageModelParameters) -> Callable[[str], str]:
    """Build the invocation callable for a language-model service.

    Delegates to the named provider adapter (or the generic
    OpenAI-compatible one): one plain request per invocation, never a
    retry. A transport failure or error response is a defect (the service
    was unreachable, not stochastic); an anticipated bad *answer* is simply
    the response, judged by the criteria.
    """
    return build_invoker(resolve_provider(parameters.provider), parameters)


def _language_model_explore_point(
    parameters: LanguageModelParameters,
) -> tuple[LanguageModelParameters, str | None]:
    """Announced degradation, never silent: a grid may span providers with
    differing structured-output, prompt-caching, or thinking support, and
    the configuration that actually runs — and its artefact — carries only
    what its provider honoured."""
    provider = resolve_provider(parameters.provider)
    notes: list[str] = []
    if parameters.response_schema is not None and not provider.supports_response_schema:
        parameters = _replace(parameters, response_schema=None)
        notes.append(
            f"provider {parameters.provider!r} has no structured-output "
            "support in this reader — the response-schema is not sent for "
            "this configuration; carry the output shape in the system "
            "prompt if the comparison should stay fair"
        )
    if parameters.prompt_caching and not provider.supports_prompt_caching:
        parameters = _replace(parameters, prompt_caching=None)
        notes.append(
            f"provider {parameters.provider!r} has no prompt-caching support "
            "in this reader — `prompt-caching:` is not sent for this "
            "configuration; its latency is measured uncached"
        )
    if parameters.thinking == "adaptive" and not provider.supports_thinking:
        parameters = _replace(parameters, thinking=None)
        notes.append(
            f"provider {parameters.provider!r} has no thinking support in "
            "this reader — `thinking:` is not sent for this configuration; "
            "its responses are sampled without deliberation"
        )
    return parameters, "; ".join(notes) if notes else None


def _language_model_type() -> ServiceTypeContract:
    """The built-in language-model entry: the first type on the generic seam."""
    return ServiceTypeContract(
        name="language-model",
        builtin=True,
        addressable=False,
        covariates={},
        parse=_validate_configuration,
        parameter_order=lambda keys: tuple(k for k in _PARAMETER_ORDER if k in keys),
        resolved_values=_resolved_values,
        provenance=resolved_provenance,
        invoker=language_model_invoker,
        accepts_configuration_key=lambda key: key in _CONFIGURATION_KEYS,
        prepare_explore_point=_language_model_explore_point,
    )
