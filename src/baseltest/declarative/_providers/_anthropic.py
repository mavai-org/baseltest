"""Anthropic: the messages protocol (system top-level, x-api-key header).

The protocol requires a generation cap on every request. It is carried by
the declared ``max-tokens:`` configuration key (resolved to its default when
unstated) and sent as the protocol's ``max_tokens`` field, recorded in
provenance like any other configuration value.

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

from baseltest.contract import FileInput, MediaKind, ServiceDeliveryError

from ._media import b64, content_blocks, mime_type, unexpected_kind
from ._protocol import Provider

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

_VERSION = "2023-06-01"

# The media kinds the Anthropic messages protocol carries as base64 source
# blocks. No audio content block exists, so `audio` is refused at the gate.
ANTHROPIC_MEDIA_KINDS: frozenset[MediaKind] = frozenset({MediaKind.IMAGE, MediaKind.DOCUMENT})


def _anthropic_block(part: FileInput) -> dict[str, Any]:
    """One Anthropic content block for a media part (base64 source)."""
    if part.kind is MediaKind.IMAGE or part.kind is MediaKind.DOCUMENT:
        block_type = "image" if part.kind is MediaKind.IMAGE else "document"
        return {
            "type": block_type,
            "source": {"type": "base64", "media_type": mime_type(part), "data": b64(part)},
        }
    raise unexpected_kind(part, "anthropic")


def _body(parameters: "LanguageModelParameters", model: str, user_input: Any) -> dict[str, Any]:
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
        "max_tokens": parameters.max_tokens,
        "messages": [{"role": "user", "content": content_blocks(user_input, _anthropic_block)}],
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
    media_kinds=ANTHROPIC_MEDIA_KINDS,
)
