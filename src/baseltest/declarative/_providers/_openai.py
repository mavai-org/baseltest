"""OpenAI: the reference chat-completions protocol."""

from typing import TYPE_CHECKING, Any

from ._protocol import (
    Provider,
    bearer_headers,
    no_constraint,
    openai_compatible_body,
    openai_compatible_extract,
)

if TYPE_CHECKING:
    from .._services import LanguageModelParameters


def _body(parameters: "LanguageModelParameters", model: str, user_prompt: str) -> dict[str, Any]:
    """The chat-completions body, with the ceiling under the current key.

    OpenAI's current chat-completions API names the output ceiling
    ``max_completion_tokens`` (the older ``max_tokens`` is rejected by
    reasoning models), so the shared OpenAI-compatible body's ``max_tokens``
    is renamed here — the one place OpenAI diverges from the Mistral/Apertus
    dialect that keeps ``max_tokens``.
    """
    body = openai_compatible_body(parameters, model, user_prompt)
    body["max_completion_tokens"] = body.pop("max_tokens")
    return body


PROVIDER = Provider(
    name="openai",
    default_endpoint="https://api.openai.com/v1/chat/completions",
    key_env_fallback="OPENAI_API_KEY",
    key_required=True,
    supports_response_schema=True,
    supports_prompt_caching=False,
    supports_thinking=False,
    constraint=no_constraint,
    body=_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
)
