"""OpenAI: the reference chat-completions protocol."""

from ._protocol import (
    Provider,
    bearer_headers,
    no_constraint,
    openai_compatible_body,
    openai_compatible_extract,
)

PROVIDER = Provider(
    name="openai",
    default_endpoint="https://api.openai.com/v1/chat/completions",
    key_env_fallback="OPENAI_API_KEY",
    key_required=True,
    supports_response_schema=True,
    supports_prompt_caching=False,
    supports_thinking=False,
    constraint=no_constraint,
    body=openai_compatible_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
)
