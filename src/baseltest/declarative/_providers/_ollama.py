"""Ollama: local inference via /api/chat (no credential, stream disabled).

A declared ``response-schema:`` passes through Ollama's ``format`` field,
which accepts a JSON Schema.
"""

from typing import TYPE_CHECKING, Any

from ._protocol import Provider, no_constraint, plain_headers

if TYPE_CHECKING:
    from .._services import LanguageModelParameters


def _body(parameters: "LanguageModelParameters", model: str, user_prompt: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": parameters.system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    options: dict[str, Any] = {}
    if parameters.temperature is not None:
        options["temperature"] = parameters.temperature
    if parameters.top_p is not None:
        options["top_p"] = parameters.top_p
    if options:
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
)
