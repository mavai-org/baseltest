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
from typing import TYPE_CHECKING, Any

from baseltest.contract import BaseltestError, ServiceDeliveryError

from .._errors import ContractConfigurationError
from . import _anthropic, _apertus, _litellm, _mistral, _ollama, _openai
from ._media import CAPABILITY_FOR, media_kinds_present
from ._protocol import (
    CAPABILITY_NAMES,
    ENV_API_KEY,
    ENV_ENDPOINT,
    ENV_MODEL,
    GENERIC,
    Provider,
    declarable_capabilities,
    honours,
)

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

_VENDOR_MODULES = (_openai, _anthropic, _ollama, _mistral, _apertus, _litellm)
PROVIDERS: dict[str, Provider] = {
    module.PROVIDER.name: module.PROVIDER for module in _VENDOR_MODULES
}

__all__ = [
    "CAPABILITY_NAMES",
    "ENV_API_KEY",
    "ENV_ENDPOINT",
    "ENV_MODEL",
    "PROVIDERS",
    "Provider",
    "ProviderResponseError",
    "build_invoker",
    "declarable_capabilities",
    "honours",
    "require_media",
    "resolve_provider",
]


def require_media(provider: Provider, declared: frozenset[str] | None, user_input: Any) -> None:
    """Refuse, before any sample, a media input this LLM service cannot carry.

    A media kind is carried when the adapter's protocol can encode it
    (``provider.media_kinds``) *and* the service declared the matching
    capability — an undeclared capability is never sent silently, the same
    rule the schema/caching/thinking gates follow. The ``file`` kind is
    deliver-to-binding only; it has no model wire form and is always refused.
    """
    for kind in media_kinds_present(user_input):
        token = CAPABILITY_FOR.get(kind)
        if token is None or kind not in provider.media_kinds:
            raise ContractConfigurationError(
                f"provider {provider.name!r} cannot carry {kind.value!r} input to the "
                "model — its request protocol has no content block for it. Choose a "
                "provider that does, or hand the file to a bound service instead."
            )
        if not honours(provider, declared, token):
            raise ContractConfigurationError(
                f"provider {provider.name!r} can carry {kind.value!r} input, but the "
                f"service has not allowed it — add `capabilities: [{token}]` to the "
                "service configuration so the media is sent (an undeclared capability "
                "is never sent silently)."
            )


class ProviderResponseError(BaseltestError):
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
            f"provider {provider.name!r} has no default endpoint — set the "
            f"{ENV_ENDPOINT} environment variable "
            "(an OpenAI-compatible chat-completions endpoint)"
        )
    return endpoint


def build_invoker(
    provider: Provider, parameters: "LanguageModelParameters"
) -> Callable[[Any], str]:
    """The invocation callable: one plain request per call, no retries."""
    capabilities = parameters.capabilities
    if parameters.response_schema is not None and not honours(
        provider, capabilities, "response-schema"
    ):
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no structured-output support in this "
            "reader: a declared `response-schema:` cannot be honoured, and silently "
            "dropping it would change what is being measured. Remove the schema, "
            "declare the capability if the endpoint honours it, or choose a "
            "provider that supports it."
        )
    if parameters.prompt_caching and not honours(provider, capabilities, "prompt-caching"):
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no prompt-caching support in this "
            "reader: `prompt-caching: true` cannot be honoured, and silently "
            "dropping it would change what is being measured. Remove the key, "
            "declare the capability if the endpoint honours it, or choose a "
            "provider that supports it."
        )
    if parameters.thinking == "adaptive" and not honours(provider, capabilities, "thinking"):
        raise ContractConfigurationError(
            f"provider {provider.name!r} has no thinking support in this reader: "
            "`thinking: adaptive` cannot be honoured, and silently dropping it "
            "would change what is being measured. Remove the key, declare the "
            "capability if the endpoint honours it, or choose a provider that "
            "supports it."
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

    def invoke(user_input: Any) -> str:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(provider.body(parameters, model, user_input)).encode("utf-8"),
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
        # A 2xx body that does not match the vendor's shape is still a
        # *delivered* response — the boundary is: provider rejection →
        # abort; delivered-but-odd response → counted failed sample with
        # the cause recorded.
        try:
            content = provider.extract(payload)
        except ServiceDeliveryError:
            raise
        except (KeyError, IndexError, TypeError) as error:
            raise ServiceDeliveryError(
                f"service delivered a response body not matching the "
                f"{provider.name} shape: {type(error).__name__}: {error}"
            ) from None
        if not isinstance(content, str):
            raise ServiceDeliveryError(
                f"service delivered a response with no text content "
                f"(the {provider.name} content field held {type(content).__name__})"
            )
        return content

    return invoke
