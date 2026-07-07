"""Named language-model provider adapters: basic integrations, nothing clever.

One module per vendor; adding a provider is one new module plus one entry
in the registry tuple below. Each adapter declares a single
:class:`Provider` value: the protocol shape of one chat request (body,
headers, response extraction), the default endpoint
(environment-overridable), the vendor's conventional credential fallback,
and whether a declared response schema can be honoured.

Deliberately absent from every adapter, as a rule and not an omission:
retries, backoff, caching, streaming, tool use. A silently retried failure
is a resampled trial and biases the observed rate — sampling independence
outranks API convenience. One invocation, one request; transport and error
responses are defects.
"""

import json
import os
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING

from .._errors import ContractConfigurationError
from . import _anthropic, _apertus, _mistral, _ollama, _openai
from ._protocol import (
    ENV_API_KEY,
    ENV_ENDPOINT,
    ENV_MODEL,
    GENERIC,
    Provider,
)

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

ANTHROPIC_REQUIRED_MAX_TOKENS = _anthropic.REQUIRED_MAX_TOKENS

_VENDOR_MODULES = (_openai, _anthropic, _ollama, _mistral, _apertus)
PROVIDERS: dict[str, Provider] = {
    module.PROVIDER.name: module.PROVIDER for module in _VENDOR_MODULES
}

__all__ = [
    "ANTHROPIC_REQUIRED_MAX_TOKENS",
    "ENV_API_KEY",
    "ENV_ENDPOINT",
    "ENV_MODEL",
    "PROVIDERS",
    "Provider",
    "build_invoker",
    "resolve_provider",
]


def resolve_provider(name: str | None) -> Provider:
    """The adapter for a declared provider name, or the generic one."""
    if name is None:
        return GENERIC
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ContractConfigurationError(
            f"unknown `provider: {name}` — supported: {', '.join(sorted(PROVIDERS))} "
            "(or omit `provider:` for a generic OpenAI-compatible endpoint)"
        )
    return provider


def _api_key(provider: Provider) -> str:
    key = os.environ.get(ENV_API_KEY, "")
    if not key and provider.key_env_fallback:
        key = os.environ.get(provider.key_env_fallback, "")
    if not key and provider.key_required:
        raise ContractConfigurationError(
            f"provider {provider.name!r} needs a credential: set {ENV_API_KEY}"
            + (f" or {provider.key_env_fallback}" if provider.key_env_fallback else "")
        )
    return key


def _resolve_endpoint(provider: Provider) -> str:
    endpoint = os.environ.get(ENV_ENDPOINT) or provider.default_endpoint
    if not endpoint:
        raise ContractConfigurationError(
            f"a language-model service without a named provider needs the "
            f"{ENV_ENDPOINT} environment variable "
            "(an OpenAI-compatible chat-completions endpoint)"
        )
    return endpoint


def build_invoker(
    provider: Provider, parameters: "LanguageModelParameters"
) -> Callable[[str], str]:
    """The invocation callable: one plain request per call, no retries."""
    if parameters.response_schema is not None and not provider.supports_response_schema:
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no structured-output support in this "
            "reader: a declared `response-schema:` cannot be honoured, and silently "
            "dropping it would change what is being measured. Remove the schema or "
            "choose a provider that supports it."
        )
    endpoint = _resolve_endpoint(provider)
    model = parameters.model or os.environ.get(ENV_MODEL)
    if not model:
        raise ContractConfigurationError(
            f"no model declared and {ENV_MODEL} is not set — declare `model:` in the "
            "service configuration or set the environment default"
        )
    headers = provider.headers(_api_key(provider))

    def invoke(user_prompt: str) -> str:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(provider.body(parameters, model, user_prompt)).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        content = provider.extract(payload)
        if not isinstance(content, str):
            raise ValueError("the provider response carried no text content")
        return content

    return invoke
