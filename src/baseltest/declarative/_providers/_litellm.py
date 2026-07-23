"""litellm: an OpenAI-compatible LLM gateway, capabilities declared by the author.

A gateway is not a vendor. It fronts many upstream models behind one
OpenAI-compatible surface, and a model *alias* names a capability the gateway
resolves — so the adapter cannot know from its protocol whether the aliased
upstream honours structured output, prompt caching, or thinking. One alias
fronts a reasoning-and-cache-capable model; the next fronts a small local one;
both arrive here. The three static capability flags are therefore ``False``:
the adapter honours nothing on its own. The contract author turns a capability
on with the service's ``capabilities:`` allowance, and this adapter's body
encodes what was turned on — that is what ``extra_declarable_capabilities``
records.

Encoding follows litellm's canonical pass-through form: ``response_format`` for
a schema (the OpenAI-compatible shape), ``cache_control`` on the system
message's content block for prompt caching, and a reasoning parameter for
thinking. The *exact* wire form a given gateway version and upstream honour is
an operational fact to confirm against the live gateway before a baseline is
trusted; the forms here are litellm's documented canon, not any one upstream's
native shape.

Two hazards a gateway invites, and this adapter's stance on each:

- **Routing that changes which model answers** — litellm fallback,
  load-balancing, mid-run failover — is inadmissible in a measured run: the
  samples would not be i.i.d. and the run would be invalid. The adapter sends
  one plain request per invocation, as every adapter does, and configures none
  of it.
- **Alias mutability.** An operator repointing an alias to a newer upstream
  leaves the recorded ``model:`` string byte-identical while the measured
  service has changed. This adapter does not try to detect that — the party
  operating the gateway owns not swapping a model silently, and a consumer that
  needs the guarantee pins the real upstream identity with a covariate.
"""

from typing import TYPE_CHECKING, Any

from ._protocol import (
    CAPABILITY_NAMES,
    OPENAI_MEDIA_KINDS,
    Provider,
    bearer_headers,
    no_constraint,
    openai_compatible_body,
    openai_compatible_extract,
)

if TYPE_CHECKING:
    from .._services import LanguageModelParameters

# litellm normalises thinking to an OpenAI-style reasoning effort across
# upstreams. baseltest's `thinking:` vocabulary is adaptive/none; "adaptive"
# maps to a mid effort here — the mapping, and whether the aliased upstream
# honours it, is the wire-form fact to confirm against the live gateway.
_ADAPTIVE_REASONING_EFFORT = "medium"


def _body(parameters: "LanguageModelParameters", model: str, user_input: Any) -> dict[str, Any]:
    """The OpenAI-compatible body, plus the encodings the author declared.

    ``response_format`` for a schema comes from the shared generic body.
    Prompt caching rewrites the system message's content to a single block
    marked ``cache_control: ephemeral`` (litellm forwards the marker to
    caching-capable upstreams); thinking adds a reasoning parameter.
    """
    body = openai_compatible_body(parameters, model, user_input)
    if parameters.prompt_caching:
        body["messages"][0]["content"] = [
            {
                "type": "text",
                "text": parameters.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    if parameters.thinking == "adaptive":
        body["reasoning_effort"] = _ADAPTIVE_REASONING_EFFORT
    return body


PROVIDER = Provider(
    name="litellm",
    default_endpoint=None,  # a gateway has no canonical host; MAVAI_LLM_ENDPOINT is required
    key_env_fallback="LITELLM_API_KEY",
    key_required=True,
    supports_response_schema=False,  # nothing is honoured by default — the alias decides
    supports_prompt_caching=False,
    supports_thinking=False,
    extra_declarable_capabilities=frozenset(CAPABILITY_NAMES),  # all three are author-declarable
    constraint=no_constraint,
    body=_body,
    headers=bearer_headers,
    extract=openai_compatible_extract,
    media_kinds=OPENAI_MEDIA_KINDS,
)
