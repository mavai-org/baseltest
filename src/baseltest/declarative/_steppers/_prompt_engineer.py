"""The ``prompt-engineer`` built-in stepper: a meta-LLM tunes the prompt.

Each iteration sends the current prompt, its score, and the per-criterion
failure breakdown with exemplars to a meta model and treats the response as
the next prompt. The resolved meta identity rides out on each proposal's
provenance for the artefact.
"""

from collections.abc import Callable, Mapping
from typing import Any

from .._errors import ContractConfigurationError
from ._context import FailureDetail, IterationResult, OptimizeContext
from ._contract import StepFunction, StepProposal

_META_PROMPT = """\
You are a prompt engineer. The user gives you a system prompt currently \
used with an LLM-backed service under probabilistic test, the pass rate \
that prompt achieved, and a breakdown of the criteria it failed with \
example failures. Propose an improved version of the prompt that \
addresses the most common failure modes for structured-output and \
instruction-following tasks — vague output shape, missing required \
fields, free-form commentary mixed into the answer. Output only the new \
system prompt. No commentary, no preamble, no surrounding quotes.\
"""


def _prompt_engineer(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.5,
    system_prompt: str = _META_PROMPT,
    target_key: str = "system-prompt",
    max_exemplars: int = 2,
) -> StepFunction:
    """A meta-LLM as prompt engineer: the previous iteration's failures drive the next prompt.

    ``provider`` and ``model`` default to the optimized service's own —
    read from the current configuration at each step, so the credentials
    the service already uses cover the meta model too and no vendor is
    silently pinned. The resolved meta identity is recorded on each
    proposal's provenance for the artefact.
    """
    if max_exemplars < 0:
        raise ContractConfigurationError(
            f"stepper 'prompt-engineer': `max-exemplars:` must be at least 0, got {max_exemplars}"
        )
    invokers: dict[tuple[str | None, str | None], Callable[[str], str]] = {}

    def meta_invoker(
        current: dict[str, Any],
    ) -> tuple[Callable[[str], str], str | None, str | None]:
        # Deferred import: this module defines the registration surface the
        # services module builds on; the provider machinery is reached only
        # when a step actually runs.
        from .._providers import build_invoker, resolve_provider
        from .._services import LanguageModelParameters

        meta_provider = provider if provider is not None else current.get("provider")
        meta_model = model if model is not None else current.get("model")
        identity = (meta_provider, meta_model)
        if identity not in invokers:
            parameters = LanguageModelParameters(
                system_prompt=system_prompt,
                provider=meta_provider,
                model=meta_model,
                temperature=temperature,
            )
            invokers[identity] = build_invoker(resolve_provider(meta_provider), parameters)
        return invokers[identity], meta_provider, meta_model

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> StepProposal:
        last = ctx.history[-1]
        invoke, meta_provider, meta_model = meta_invoker(current)
        provenance: Mapping[str, object] = {
            "metaProvider": meta_provider or "openai-compatible",
            "metaModel": meta_model or "(environment default)",
            "metaTemperature": temperature,
        }
        suggestion = invoke(_meta_message(last, target_key, max_exemplars)).strip()
        if not suggestion:
            # a meta model with nothing to propose stops the run
            return StepProposal(config=None, provenance=provenance)
        return StepProposal(config={**current, target_key: suggestion}, provenance=provenance)

    return advance


def _meta_message(last: IterationResult, target_key: str, max_exemplars: int) -> str:
    """The meta-LLM's user message: prompt, score, and the failure breakdown."""
    sections = [
        "Current system prompt:",
        str(last.config.get(target_key, "")),
        "",
        f"Pass rate achieved: {last.summary.pass_rate:.2f} "
        f"({last.passes} of {last.samples} samples passed)",
    ]
    breakdown = _failure_breakdown(last.failures_by_criterion, max_exemplars)
    if breakdown:
        sections.extend(["", "Failure breakdown:", *breakdown])
    sections.extend(["", "Suggest an improved version."])
    return "\n".join(sections)


def _failure_breakdown(failures: Mapping[str, FailureDetail], max_exemplars: int) -> list[str]:
    lines: list[str] = []
    by_count = sorted(failures.items(), key=lambda item: item[1].count, reverse=True)
    for name, detail in by_count:
        lines.append(f'- criterion "{name}" failed {detail.count} time(s).')
        for exemplar in detail.exemplars[:max_exemplars]:
            lines.append(f'    - input "{exemplar.input}" → {exemplar.reason}')
    return lines
