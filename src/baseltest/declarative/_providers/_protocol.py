"""The provider model and the shared OpenAI-compatible protocol shapes.

Vendor modules compose these; a vendor with a genuinely different wire
protocol (anthropic, ollama) declares its own body/extract functions in
its own module instead.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

ENV_ENDPOINT = "MAVAI_LLM_ENDPOINT"
ENV_API_KEY = "MAVAI_LLM_API_KEY"
ENV_MODEL = "MAVAI_LLM_MODEL"

# The provider-neutral capability vocabulary an author may name in a
# service's `capabilities:` allowance. Each maps to one configuration key
# whose honouring is capability-gated: `response-schema:`, `prompt-caching:`,
# `thinking:`.
CAPABILITY_NAMES: tuple[str, ...] = ("response-schema", "prompt-caching", "thinking")

BodyBuilder = Callable[["LanguageModelParameters", str, str], dict[str, Any]]
HeaderBuilder = Callable[[str], dict[str, str]]
Extractor = Callable[[dict[str, Any]], Any]
Constraint = Callable[["LanguageModelParameters"], str | None]


def no_constraint(_parameters: "LanguageModelParameters") -> str | None:
    """The default vendor constraint: every configuration combination is fine."""
    return None


@dataclass(frozen=True, slots=True)
class Provider:
    """One vendor adapter: protocol shape, defaults, and capability support.

    Attributes:
        name: The `provider:` value contract authors declare.
        default_endpoint: Where requests go when the environment does not
            override; ``None`` means an endpoint is mandatory (generic).
        key_env_fallback: The vendor's conventional credential variable,
            consulted when the family variable is unset.
        key_required: Whether a missing credential is a load-time refusal.
        supports_response_schema: Whether a declared ``response-schema:``
            can be honoured; when ``False``, declaring one is refused at
            load — never silently dropped.
        supports_prompt_caching: Whether ``prompt-caching: true`` can be
            honoured; same refusal rule as the schema.
        supports_thinking: Whether ``thinking: adaptive`` can be honoured;
            same refusal rule as the schema.
        extra_declarable_capabilities: Capabilities beyond the statically
            supported set that an author may turn on with a service's
            ``capabilities:`` allowance — the set the adapter's body can
            *encode on demand* but does not honour by default. Empty for a
            vendor adapter (its support is static and known); populated for a
            gateway adapter, whose upstream capability the author declares
            because the protocol cannot reveal it. A capability in neither
            the supported nor this set is refused when declared.
        constraint: The vendor's own veto over an otherwise-valid
            configuration combination: ``parameters -> refusal message`` or
            ``None`` when the combination is fine. Checked at load time.
        body: Composes one request body from (parameters, model, prompt).
        headers: Composes the request headers from the resolved credential.
        extract: Pulls the response text out of the vendor's reply shape.
    """

    name: str
    default_endpoint: str | None
    key_env_fallback: str | None
    key_required: bool
    supports_response_schema: bool
    supports_prompt_caching: bool
    supports_thinking: bool
    constraint: Constraint
    body: BodyBuilder
    headers: HeaderBuilder
    extract: Extractor
    extra_declarable_capabilities: frozenset[str] = frozenset()


def _statically_supported(provider: Provider) -> frozenset[str]:
    """The capabilities the adapter honours without any author declaration."""
    supported = set()
    if provider.supports_response_schema:
        supported.add("response-schema")
    if provider.supports_prompt_caching:
        supported.add("prompt-caching")
    if provider.supports_thinking:
        supported.add("thinking")
    return frozenset(supported)


def declarable_capabilities(provider: Provider) -> frozenset[str]:
    """The capabilities an author may assert via a service's ``capabilities:``.

    A capability is declarable when the adapter's body can put it on the wire:
    the statically supported set (already honoured, so declaring it is a
    redundant no-op) widened by whatever the adapter can encode on demand. An
    adapter that deliberately withholds a capability — apertus's hosted
    endpoint declines structured output — leaves it out of both, so declaring
    it there is refused rather than silently overriding the caution.
    """
    return _statically_supported(provider) | provider.extra_declarable_capabilities


def honours(provider: Provider, declared: frozenset[str] | None, capability: str) -> bool:
    """Effective support: honoured by default, or turned on by the author.

    The single question both the refuse-at-load (measure/test) and the
    degrade-with-note (explore) paths ask, so they stay consistent. The
    declarable gate runs at parse time, so any capability that reaches here in
    ``declared`` is one the adapter can encode — nothing downstream consults
    the raw static flag.
    """
    if capability in _statically_supported(provider):
        return True
    return declared is not None and capability in declared


def bearer_headers(key: str) -> dict[str, str]:
    """Authorization: Bearer — the OpenAI-compatible convention."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def plain_headers(_key: str) -> dict[str, str]:
    """No credential header (local inference)."""
    return {"Content-Type": "application/json"}


def openai_compatible_body(
    parameters: "LanguageModelParameters", model: str, user_prompt: str
) -> dict[str, Any]:
    """The chat-completions request body, with structured output when declared."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": parameters.system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": parameters.max_tokens,
    }
    if parameters.temperature is not None:
        body["temperature"] = parameters.temperature
    if parameters.top_p is not None:
        body["top_p"] = parameters.top_p
    if parameters.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": parameters.response_schema},
        }
    return body


def openai_compatible_extract(body: dict[str, Any]) -> Any:
    """choices[0].message.content."""
    return body["choices"][0]["message"]["content"]


GENERIC = Provider(
    name="openai-compatible",
    default_endpoint=None,
    key_env_fallback=None,
    key_required=False,
    supports_response_schema=True,
    supports_prompt_caching=False,
    supports_thinking=False,
    constraint=no_constraint,
    body=openai_compatible_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
)
