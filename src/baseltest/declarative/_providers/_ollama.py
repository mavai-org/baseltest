"""Ollama: local inference via /api/chat (no credential, stream disabled).

A declared ``response-schema:`` passes through Ollama's ``format`` field,
which accepts a JSON Schema.
"""

from typing import TYPE_CHECKING, Any

from baseltest.contract import FileInput, MediaKind

from ._media import b64, message_parts
from ._protocol import Provider, no_constraint, plain_headers

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

# Ollama carries images as a base64 array on the message, not as inline
# content blocks; it has no document or audio form, so those are refused at
# the gate.
OLLAMA_MEDIA_KINDS: frozenset[MediaKind] = frozenset({MediaKind.IMAGE})


def _ollama_user_message(user_input: Any) -> dict[str, Any]:
    """Ollama's user message: text in ``content``, images in an ``images`` array."""
    parts = message_parts(user_input)
    text = "".join(part for part in parts if isinstance(part, str))
    images = [b64(part) for part in parts if isinstance(part, FileInput)]
    message: dict[str, Any] = {"role": "user", "content": text}
    if images:
        message["images"] = images
    return message


def _body(parameters: "LanguageModelParameters", model: str, user_input: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": parameters.system_prompt},
            _ollama_user_message(user_input),
        ],
    }
    # Ollama names the output ceiling `num_predict`, nested under `options`.
    options: dict[str, Any] = {"num_predict": parameters.max_tokens}
    if parameters.temperature is not None:
        options["temperature"] = parameters.temperature
    if parameters.top_p is not None:
        options["top_p"] = parameters.top_p
    body["options"] = options
    if parameters.response_schema is not None:
        body["format"] = parameters.response_schema
    return body


def _extract(body: dict[str, Any]) -> Any:
    return body["message"]["content"]


PROVIDER = Provider(
    name="ollama",
    default_endpoint="http://localhost:11434/api/chat",
    key_env_fallback=None,
    key_required=False,
    supports_response_schema=True,
    supports_prompt_caching=False,
    supports_thinking=False,
    constraint=no_constraint,
    body=_body,
    headers=plain_headers,
    extract=_extract,
    media_kinds=OLLAMA_MEDIA_KINDS,
)
