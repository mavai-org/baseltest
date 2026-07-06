"""Anthropic: the messages protocol (system top-level, x-api-key header).

The protocol requires a generation cap on every request. The family defers
token vocabulary to its established token concepts, so this adapter pins
the protocol-required value at a documented constant, recorded in
provenance whenever the adapter is used.

Structured output is not offered by this adapter yet; a declared
``response-schema:`` is refused at load rather than silently dropped.
"""

from typing import TYPE_CHECKING, Any

from ._protocol import Provider

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

REQUIRED_MAX_TOKENS = 4096
_VERSION = "2023-06-01"


def _body(parameters: "LanguageModelParameters", model: str, user_prompt: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "system": parameters.system_prompt,
        "max_tokens": REQUIRED_MAX_TOKENS,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if parameters.temperature is not None:
        body["temperature"] = parameters.temperature
    return body


def _headers(key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": _VERSION,
    }


def _extract(body: dict[str, Any]) -> Any:
    return body["content"][0]["text"]


PROVIDER = Provider(
    name="anthropic",
    default_endpoint="https://api.anthropic.com/v1/messages",
    key_env_fallback="ANTHROPIC_API_KEY",
    key_required=True,
    supports_response_schema=False,
    body=_body,
    headers=_headers,
    extract=_extract,
)
