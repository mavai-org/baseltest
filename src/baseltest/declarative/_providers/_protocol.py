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

BodyBuilder = Callable[["LanguageModelParameters", str, str], dict[str, Any]]
HeaderBuilder = Callable[[str], dict[str, str]]
Extractor = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class Provider:
    """One vendor adapter: protocol shape, defaults, and schema support.

    Attributes:
        name: The `provider:` value task authors declare.
        default_endpoint: Where requests go when the environment does not
            override; ``None`` means an endpoint is mandatory (generic).
        key_env_fallback: The vendor's conventional credential variable,
            consulted when the family variable is unset.
        key_required: Whether a missing credential is a load-time refusal.
        supports_response_schema: Whether a declared ``response-schema:``
            can be honoured; when ``False``, declaring one is refused at
            load — never silently dropped.
        body: Composes one request body from (parameters, model, prompt).
        headers: Composes the request headers from the resolved credential.
        extract: Pulls the response text out of the vendor's reply shape.
    """

    name: str
    default_endpoint: str | None
    key_env_fallback: str | None
    key_required: bool
    supports_response_schema: bool
    body: BodyBuilder
    headers: HeaderBuilder
    extract: Extractor


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
    }
    if parameters.temperature is not None:
        body["temperature"] = parameters.temperature
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
    body=openai_compatible_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
)
