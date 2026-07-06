"""Apertus: the fully open Swiss model (EPFL, ETH Zürich, CSCS; 2025).

Served OpenAI-compatibly. The default endpoint is the Public AI inference
utility, which hosts Apertus for public access; self-hosters (the weights
are open — vLLM serves them with the same protocol) point
``MAVAI_LLM_ENDPOINT`` at their own deployment instead.

Structured output is not asserted for the hosted endpoint, so a declared
``response-schema:`` is refused at load rather than passed through
unverified; self-hosted deployments that support it can use the generic
``openai``-compatible path (omit ``provider:``) against their endpoint.
"""

from ._protocol import (
    Provider,
    bearer_headers,
    openai_compatible_body,
    openai_compatible_extract,
)

PROVIDER = Provider(
    name="apertus",
    default_endpoint="https://api.publicai.co/v1/chat/completions",
    key_env_fallback="PUBLICAI_API_KEY",
    key_required=True,
    supports_response_schema=False,
    body=openai_compatible_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
)
