"""The ``prompt-engineer`` built-in stepper: a meta-LLM tunes the prompt.

Each iteration renders the run's ledger and the pooled postcondition
standings to a meta model, which returns declared, separable edits and the
revised prompt they apply to. The resolved meta identity, the accumulated
edit ledger and the meta model's token spend ride out on the proposal's
provenance for the artefact.

Two policies live here rather than in the loop, because they are *search*
policy and belong to the algorithm that chose them:

- **The incumbent, not the last.** Edits apply to the best configuration
  measured so far, so a regression is not inherited by every iteration
  that follows it. The loop cannot impose this on every stepper — a
  sweep that stepped from the best would never advance past it.
- **What the tuner may see.** ``withhold-criteria`` keeps named criteria
  out of the message entirely. If the criteria the tuner *can* see climb
  while the withheld ones do not, that divergence is the signature of a
  prompt fitted to the measure rather than to the requirement.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from baseltest.contract import Reply

from .._errors import ContractConfigurationError
from ._context import OptimizeContext
from ._contract import StepFunction, StepProposal
from ._engineer_message import LedgerEntry, ProposedEdit, compose

_META_PROMPT = """\
You are a prompt engineer tuning the system prompt of an LLM-backed \
service under probabilistic test. You are given the current prompt, the \
per-criterion evidence from the most recent run, and the history of \
earlier runs with the edits that produced them.

The evidence is a formal statement of how the service failed its \
contract: which check, of which form, at which path, and what was \
obtained. Read it as a specification, not as a description.

Propose few, separable edits. Each edit names the criteria it targets and \
states the hypothesis it tests — the mechanism you believe is at fault. \
Small, attributable changes are worth more than a good rewrite, because a \
rewrite cannot be credited or undone.

Use the ledger. An edit that has already been tried and did not help \
should not be proposed again in the same form. A criterion that was \
passing and is now failing is a regression your last edit likely caused; \
say so and address it.

You do not decide whether a step worked. The harness measures that. \
Report your hypothesis, not your confidence in it.

Satisfying a check without meeting the requirement it exists to detect is \
a failure, not a success. If a check could be passed by a response that \
is plainly wrong, say so rather than exploiting it.

If the evidence does not describe a prompt problem — the contract is \
missing a check it should state, or the model appears not to possess the \
capability the contract requires — reply with \
{"verdict": "not-a-prompt-problem", "reason": "..."} instead of an edit. \
That is a more useful answer than a prompt change.

Otherwise reply with a single JSON object and nothing else, in exactly \
this shape:

{"assessment": "one sentence on what the evidence shows",
 "edits": [{"id": "e1", "targets": ["criterion name"],
            "hypothesis": "why this fails", "change": "what this edit does"}],
 "prompt": "the full revised system prompt"}\
"""

_NOT_A_PROMPT_PROBLEM = "not-a-prompt-problem"


def _prompt_engineer(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.5,
    system_prompt: str = _META_PROMPT,
    target_key: str = "system-prompt",
    max_exemplars: int = 2,
    withhold_criteria: str = "",
) -> StepFunction:
    """A meta-LLM as prompt engineer: the run's whole evidence drives the next prompt.

    ``provider`` and ``model`` default to the optimized service's own —
    read from the current configuration at each step, so the credentials
    the service already uses cover the meta model too and no vendor is
    silently pinned. The resolved meta identity, the edit ledger and the
    meta model's token spend are recorded on each proposal's provenance
    for the artefact.

    ``withhold-criteria`` is a comma-separated list of criterion names the
    meta model never sees — the run's control group against a prompt
    tuned to the measure rather than to the requirement. Empty by default:
    withholding evidence is a deliberate act, never a silent one.
    """
    if max_exemplars < 0:
        raise ContractConfigurationError(
            f"stepper 'prompt-engineer': `max-exemplars:` must be at least 0, got {max_exemplars}"
        )
    withheld = frozenset(name.strip() for name in withhold_criteria.split(",") if name.strip())
    invokers: dict[tuple[str | None, str | None], Callable[[str], str | Reply]] = {}
    # The stepper's own state, in the factory's closure — the framework
    # carries no stepper state of its own. The ledger is append-only:
    # entries are written once and never revised, which is what keeps the
    # rendered prefix stable and the run's record honest.
    ledger: list[LedgerEntry] = []
    tokens = _TokenTally()

    def meta_invoker(
        current: dict[str, Any],
    ) -> tuple[Callable[[str], str | Reply], str | None, str | None]:
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
        invoke, meta_provider, meta_model = meta_invoker(current)
        # The incumbent, not the last measurement: edits apply to the best
        # prompt so far, so a regression is tried and abandoned rather than
        # inherited by everything after it.
        incumbent = ctx.best if ctx.best is not None else ctx.history[-1]
        message = compose(tuple(ledger), ctx, incumbent, target_key, withheld, max_exemplars)
        answer = invoke(message)
        # The meta model's endpoint may report usage; only the text is the
        # proposal. Meta-call tokens are not sample cost — they are the
        # tuner's own spend, recorded separately so an operator can see
        # what the search cost beside what the samples cost.
        if isinstance(answer, Reply):
            tokens.add(answer.total_tokens)
        text = (answer.text if isinstance(answer, Reply) else answer).strip()

        def residue(**extra: object) -> Mapping[str, object]:
            block: dict[str, object] = {
                "metaProvider": meta_provider or "openai-compatible",
                "metaModel": meta_model or "(environment default)",
                "metaTemperature": temperature,
            }
            if withheld:
                block["withheldCriteria"] = ", ".join(sorted(withheld))
            if tokens.total is not None:
                block["metaTokens"] = tokens.total
            if ledger:
                block["editLedger"] = _rendered_ledger(ledger)
            block.update(extra)
            return block

        if not text:
            # a meta model with nothing to propose stops the run
            return StepProposal(config=None, provenance=residue(stoppingReason="no-proposal"))
        parsed = _parse(text)
        if isinstance(parsed, _Refusal):
            # An expected failure, not a defect: the run stops with the
            # reason stated rather than retrying behind the operator's back.
            return StepProposal(
                config=None,
                provenance=residue(stoppingReason=parsed.reason, stoppingDetail=parsed.detail),
            )
        ledger.append(
            LedgerEntry(iteration=ctx.iteration, assessment=parsed.assessment, edits=parsed.edits)
        )
        return StepProposal(
            config={**incumbent.config, target_key: parsed.prompt},
            provenance=residue(),
        )

    return advance


class _TokenTally:
    """The meta model's own spend across the run, when its endpoint reports it."""

    def __init__(self) -> None:
        self.total: int | None = None

    def add(self, reported: int | None) -> None:
        if reported is not None:
            self.total = (self.total or 0) + reported


class _Proposal:
    """A well-formed proposal: the assessment, its edits, and the revised prompt."""

    __slots__ = ("assessment", "edits", "prompt")

    def __init__(self, assessment: str, edits: tuple[ProposedEdit, ...], prompt: str) -> None:
        self.assessment = assessment
        self.edits = edits
        self.prompt = prompt


class _Refusal:
    """Why no proposal was taken from this reply: the stopping reason and its detail."""

    __slots__ = ("detail", "reason")

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail


def _parse(text: str) -> _Proposal | _Refusal:
    """The meta model's reply as a proposal, a declared refusal, or a malformed stop."""
    try:
        payload = json.loads(_unfenced(text))
    except json.JSONDecodeError as error:
        return _Refusal("malformed-proposal", f"the reply was not JSON: {error}")
    if not isinstance(payload, dict):
        return _Refusal("malformed-proposal", "the reply was not a JSON object")
    if payload.get("verdict") == _NOT_A_PROMPT_PROBLEM:
        return _Refusal(_NOT_A_PROMPT_PROBLEM, str(payload.get("reason", "(no reason stated)")))
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _Refusal("malformed-proposal", "the reply carried no `prompt` string")
    return _Proposal(
        assessment=str(payload.get("assessment", "(no assessment stated)")),
        edits=_edits(payload.get("edits")),
        prompt=prompt.strip(),
    )


def _edits(raw: object) -> tuple[ProposedEdit, ...]:
    """The declared edits, defaulted field by field.

    A reply that carries a prompt but describes it poorly is still usable —
    the prompt is what the service runs. What a thin edit costs is
    attribution, and the ledger records exactly what was declared so that
    cost is visible rather than papered over.
    """
    if not isinstance(raw, list):
        return ()
    edits = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        targets = item.get("targets")
        edits.append(
            ProposedEdit(
                id=str(item.get("id", f"e{index}")),
                targets=tuple(str(t) for t in targets) if isinstance(targets, list) else (),
                hypothesis=str(item.get("hypothesis", "(none stated)")),
                change=str(item.get("change", "(none stated)")),
            )
        )
    return tuple(edits)


def _unfenced(text: str) -> str:
    """The reply's JSON, with a markdown code fence stripped if one wraps it.

    Lenient parsing of a well-known wrapper, not a retry: nothing is
    re-asked and nothing is guessed at, so a genuinely malformed reply
    still stops the run.
    """
    if not text.startswith("```"):
        return text
    body = text.split("\n", 1)[1] if "\n" in text else ""
    fence = body.rfind("```")
    return body[:fence] if fence != -1 else body


def _rendered_ledger(ledger: list[LedgerEntry]) -> str:
    """The whole run's edits as one artefact-bound string.

    The artefact's ``stepper:`` block is last-wins by design, so a
    per-iteration record cannot live there without amending the
    interchange schema. Rendering the accumulated ledger into a single
    value keeps "what changed, and when" answerable within the shape the
    format already has.
    """
    lines = []
    for entry in ledger:
        for edit in entry.edits:
            lines.append(
                f"iteration {entry.iteration} [{edit.id}] "
                f"targets={'/'.join(edit.targets) or '(unstated)'}: "
                f"{edit.change} — hypothesis: {edit.hypothesis}"
            )
    return "\n".join(lines)
