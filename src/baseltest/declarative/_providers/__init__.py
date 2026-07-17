"""Named language-model provider adapters: basic integrations, nothing clever.

One module per vendor; adding a provider is one new module plus one entry
in the registry tuple below. Each adapter declares a single
:class:`Provider` value: the protocol shape of one chat request (body,
headers, response extraction), the default endpoint
(environment-overridable), the vendor's conventional credential fallback,
and whether a declared response schema can be honoured.

Deliberately absent from every adapter, as a rule and not an omission:
retries, backoff, client-side response caching, streaming, tool use. A
silently retried failure is a resampled trial and biases the observed rate —
sampling independence outranks API convenience. One invocation, one request;
transport and error responses are defects. (Provider-side prompt caching is
different: it is a declared configuration factor — ``prompt-caching:`` —
fixed per configuration and part of the drift-checked identity, not a
convenience the adapter reaches for on its own.)
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING

from baseltest.contract import ServiceDeliveryError

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
    "ProviderResponseError",
    "build_invoker",
    "resolve_provider",
]


class ProviderResponseError(Exception):
    """The provider rejected the request — a configuration defect, never a sample.

    A client-side error status (a rejected schema, an unknown model id,
    an expired credential) says the *request* was wrong, not that the
    service is stochastic — counting it as failed samples would render a
    verdict about nothing. The abort must be *investigable*, so this
    error carries the provider, the status, and the response body instead
    of a bare "HTTP Error 400".

    Failed *delivery* is different: an unreachable service or a
    server-side error is a failed sample (the service did not deliver),
    raised as :class:`baseltest.contract.ServiceDeliveryError` and counted
    against the criteria with its cause as the reason.
    """

    def __init__(self, provider: str, status: int, detail: str) -> None:
        self.provider = provider
        self.status = status
        self.detail = detail
        super().__init__(
            f"provider {provider!r} returned HTTP {status} — a defect, not a "
            f"sample; the run is aborted. The provider said: {detail or '(empty body)'}"
        )


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
    if parameters.prompt_caching and not provider.supports_prompt_caching:
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no prompt-caching support in this "
            "reader: `prompt-caching: true` cannot be honoured, and silently "
            "dropping it would change what is being measured. Remove the key or "
            "choose a provider that supports it."
        )
    if parameters.thinking == "adaptive" and not provider.supports_thinking:
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no thinking support in this reader: "
            "`thinking: adaptive` cannot be honoured, and silently dropping it "
            "would change what is being measured. Remove the key or choose a "
            "provider that supports it."
        )
    refusal = provider.constraint(parameters)
    if refusal is not None:
        raise ContractConfigurationError(f"provider {provider.name!r}: {refusal}")
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
        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = error.read().decode("utf-8", "replace")[:2000]
            except OSError:
                detail = ""
            if error.code >= 500:
                # The service answered that it is failing: a failed
                # delivery, counted as a failed sample with its cause.
                raise ServiceDeliveryError(
                    f"service failed to deliver: {provider.name} answered "
                    f"HTTP {error.code} at {endpoint}" + (f" — {detail[:200]}" if detail else "")
                ) from None
            raise ProviderResponseError(provider.name, error.code, detail) from None
        except urllib.error.URLError as error:
            # No response at all — DNS, refused connection, timeout: the
            # service is unreachable, which is a failed delivery too.
            raise ServiceDeliveryError(
                f"service unreachable at {endpoint}: {error.reason}"
            ) from None
        content = provider.extract(payload)
        if not isinstance(content, str):
            raise ValueError("the provider response carried no text content")
        return content

    return invoke
