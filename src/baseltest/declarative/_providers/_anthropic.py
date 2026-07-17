"""Anthropic: the messages protocol (system top-level, x-api-key header).

The protocol requires a generation cap on every request. The family defers
token vocabulary to its established token concepts, so this adapter pins
the protocol-required value at a documented constant, recorded in
provenance whenever the adapter is used.

A declared ``response-schema:`` is passed through the protocol's
structured-output mechanism (``output_config.format`` with a JSON
schema); the schema itself is the author's and travels verbatim — the
endpoint validates it, per the basic-adapter rule.

This adapter is the first realisation of the provider-neutral
``prompt-caching:`` and ``thinking:`` configuration keys.
``prompt-caching: true`` marks the system block ``cache_control:
ephemeral`` — the first, cache-writing invocation simply lands as the
slowest recorded latency point, and a cache-TTL expiry mid-run mixes
read-mode and write-mode samples in one latency population (absorbed
descriptively by the empirical percentiles; a bimodal p99 under caching
is that, not service degradation). ``thinking: adaptive`` passes the
protocol's adaptive-thinking mode through verbatim. With thinking
enabled the protocol constrains sampling parameters, so the combination
with an explicit ``temperature:`` or ``top-p:`` is refused at load time
via the vendor constraint below.
"""

from typing import TYPE_CHECKING, Any

from baseltest.contract import ServiceDeliveryError

from ._protocol import Provider

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

REQUIRED_MAX_TOKENS = 4096
_VERSION = "2023-06-01"


def _body(parameters: "LanguageModelParameters", model: str, user_prompt: str) -> dict[str, Any]:
    system: Any = parameters.system_prompt
    if parameters.prompt_caching:
        system = [
            {
                "type": "text",
                "text": parameters.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    body: dict[str, Any] = {
        "model": model,
        "system": system,
        "max_tokens": REQUIRED_MAX_TOKENS,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if parameters.thinking == "adaptive":
        body["thinking"] = {"type": "adaptive"}
    if parameters.temperature is not None:
        body["temperature"] = parameters.temperature
    if parameters.top_p is not None:
        body["top_p"] = parameters.top_p
    if parameters.response_schema is not None:
        body["output_config"] = {
            "format": {"type": "json_schema", "schema": parameters.response_schema}
        }
    return body


def _constraint(parameters: "LanguageModelParameters") -> str | None:
    if parameters.thinking == "adaptive" and (
        parameters.temperature is not None or parameters.top_p is not None
    ):
        return (
            "the anthropic API constrains sampling parameters when thinking is "
            "enabled — `thinking: adaptive` cannot be combined with an explicit "
            "`temperature:` or `top-p:`; remove the sampling key or set "
            "`thinking: none`"
        )
    return None


def _headers(key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": _VERSION,
    }


def _extract(body: dict[str, Any]) -> Any:
    # With thinking enabled the assistant text is not the first content
    # block — `thinking` (and possibly `redacted_thinking`) blocks precede
    # it. The assistant text is the first block of type `text`, wherever
    # it sits.
    for block in body["content"]:
        if block.get("type") == "text":
            return block["text"]
    kinds = ", ".join(str(block.get("type")) for block in body["content"]) or "(none)"
    stop_reason = body.get("stop_reason")
    raise ServiceDeliveryError(
        "anthropic delivered a response with no text content block "
        f"(blocks: {kinds}; stop_reason: {stop_reason})"
    )


PROVIDER = Provider(
    name="anthropic",
    default_endpoint="https://api.anthropic.com/v1/messages",
    key_env_fallback="ANTHROPIC_API_KEY",
    key_required=True,
    supports_response_schema=True,
    supports_prompt_caching=True,
    supports_thinking=True,
    constraint=_constraint,
    body=_body,
    headers=_headers,
    extract=_extract,
)
