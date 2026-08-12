"""The ``prompt-engineer``'s ledger and the message it renders.

The stepper keeps a **ledger**, not a conversation. Carrying the meta
model's own message history forward would let it anchor on hypotheses it
has already asserted, and — decisively here — a transcript is not a
record: it cannot be emitted, pruned, or re-rendered, so it cannot answer
what the tuner knew when it proposed a change. The model's reasoning is
not lost by dropping the transcript, it is relocated: the ``hypothesis``
it declares with every edit *is* the reasoning, held as data the framework
owns.

Two forces shape the message layout and they pull opposite ways. Attention
favours the end of a long context; prefix caching requires everything
stable to precede everything that changes. The layout satisfies both::

    [1] preamble          stable — the criteria in play and the protocol
    [2] ledger            append-only, byte-identical across turns
    [3] recency digest    the last edit and what actually followed it
    [4] current evidence  this iteration's pooled standings
    [5] regression watch  criteria that were passing and now are not
    [6] instruction       propose edits, in the declared shape

Blocks [1]–[2] must render identically on every call that shares a ledger
prefix — that is what makes the prefix cacheable, and what makes the
ledger a record rather than a working note. Block [3] is a deliberate
*copy* of the newest entry, never a move: the newest entry is the highest
-value historical fact and would otherwise sit at the tail of the ledger,
where long contexts attend least. Hoisting it out would leave the run's
record with a hole.
"""

from dataclasses import dataclass

from ._context import CheckGroup, CriterionEvidence, IterationResult, OptimizeContext

_RULE = "─" * 60


@dataclass(frozen=True, slots=True)
class ProposedEdit:
    """One declared, separable change the meta model proposed.

    Few, separable, individually-hypothesised edits are a design
    constraint rather than a style preference: an opaque rewrite cannot be
    credited, blamed, or undone, so a run of rewrites can never say which
    change did the work.
    """

    id: str
    targets: tuple[str, ...]
    hypothesis: str
    change: str


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One completed proposal: the iteration it produced and its edits.

    Immutable once written. The outcome is deliberately *not* stored — it
    is derived from the run's history at render time, so an entry can
    never disagree with what the run actually measured.
    """

    iteration: int
    assessment: str
    edits: tuple[ProposedEdit, ...]


def compose(
    ledger: tuple[LedgerEntry, ...],
    ctx: OptimizeContext,
    incumbent: IterationResult,
    target_key: str,
    withheld: frozenset[str],
    max_excerpts: int,
) -> str:
    """The meta model's user message, in the six-block layout."""
    current = ctx.history[-1]
    blocks = [
        _preamble(ctx, current, withheld),
        _ledger(ledger, ctx),
        _digest(ledger, ctx),
        _current(current, withheld, max_excerpts),
        _regressions(current, ctx.best, withheld),
        _instruction(incumbent, target_key),
    ]
    return "\n\n".join(block for block in blocks if block)


def _preamble(ctx: OptimizeContext, current: IterationResult, withheld: frozenset[str]) -> str:
    """Block [1] — stable across the run: the criteria in play, and the budget."""
    names = [e.name for e in current.evidence if e.name not in withheld]
    lines = [
        f"{_RULE}\nCONTRACT\n{_RULE}",
        "Criteria under test: " + (", ".join(names) if names else "(none reported)"),
        f"Iterations in this run: {ctx.iteration + ctx.iterations_remaining}.",
    ]
    return "\n".join(lines)


def _ledger(ledger: tuple[LedgerEntry, ...], ctx: OptimizeContext) -> str:
    """Block [2] — append-only. Every entry here has a measured outcome."""
    lines = [f"{_RULE}\nLEDGER — what has been tried, in order\n{_RULE}"]
    total = ctx.iteration + ctx.iterations_remaining
    lines.append(f"Iteration 0 of {total} (baseline, no edits): {_outcome(ctx.history[0])}.")
    for entry in ledger:
        lines.append("")
        lines.append(f"Iteration {entry.iteration} of {total}: {entry.assessment}")
        for edit in entry.edits:
            lines.append(
                f"  [{edit.id}] targets {', '.join(edit.targets) or '(unstated)'} — "
                f"{edit.change} (hypothesis: {edit.hypothesis})"
            )
        result = ctx.history[entry.iteration]
        before = ctx.history[entry.iteration - 1]
        lines.append(f"  result: {_outcome(result)} (from {_outcome(before)}).")
        broke = _regressed(result, before)
        if broke:
            lines.append(f"  regressed against the previous iteration: {', '.join(broke)}.")
    return "\n".join(lines)


def _digest(ledger: tuple[LedgerEntry, ...], ctx: OptimizeContext) -> str:
    """Block [3] — the newest entry restated beside the current evidence.

    A copy, not a move: what was changed and what changed as a result only
    mean anything read together, and the ledger stays complete.
    """
    if not ledger:
        return (
            f"{_RULE}\nMOST RECENT CHANGE\n{_RULE}\n"
            "None — this is the first proposal of the run, and the evidence "
            "below is the baseline prompt's."
        )
    entry = ledger[-1]
    result = ctx.history[entry.iteration]
    before = ctx.history[entry.iteration - 1]
    lines = [
        f"{_RULE}\nMOST RECENT CHANGE — you made this, and this is what followed\n{_RULE}",
        f"At iteration {entry.iteration} you judged: {entry.assessment}",
    ]
    for edit in entry.edits:
        lines.append(f"  [{edit.id}] {edit.change}")
        lines.append(f"      you expected: {edit.hypothesis}")
        lines.append(f"      targeting: {', '.join(edit.targets) or '(unstated)'}")
    lines.append(f"Result: {_outcome(result)}, from {_outcome(before)}.")
    return "\n".join(lines)


def _current(current: IterationResult, withheld: frozenset[str], max_excerpts: int) -> str:
    """Block [4] — this iteration's pooled standings, criterion by criterion.

    Declared operands are withheld: publishing a criterion's own text to
    the tuner is a policy question this stepper does not decide, and an
    input's expected value is an answer key. What the *service* returned
    is not contract text and carries no such hazard, so obtained values
    are the evidence that travels.
    """
    lines = [f"{_RULE}\nCURRENT EVIDENCE — the run just measured\n{_RULE}"]
    shown = [e for e in current.evidence if e.name not in withheld]
    if not shown:
        return ""
    for criterion in shown:
        lines.append("")
        lines.append(f"criterion {criterion.name!r}: {_rate(criterion)}")
        for group in criterion.groups:
            if not group.failed:
                # Stated, not omitted: a group that now holds is how the
                # tuner sees an earlier edit pay off. Dropping it would
                # make progress look like absence.
                lines.append(f"  {_group_heading(group)}")
                continue
            lines.append(f"  {_group_heading(group)}")
            for value in group.observed[:max_excerpts]:
                verdict = "held" if value.held else "did not hold"
                lines.append(f"      returned {value.excerpt!r} ×{value.count} — {verdict}")
    return "\n".join(lines)


def _group_heading(group: CheckGroup) -> str:
    """One pooled group as a single statement about the service.

    An input-declared group states *how many* inputs it covers and never
    which: each such check is ``n = 1``, and only the pattern across them
    is a fact about the service rather than about one answer.
    """
    form = group.form or "check"
    where = f" at {group.path}" if group.path else ""
    optional = " (optional — partial credit)" if group.optional else ""
    if group.provenance == "input":
        scope = f"{group.checks} input-stated {form} check(s){where} across {group.inputs} input(s)"
    else:
        scope = f"criterion-stated {form} check(s){where}"
    return f"{scope}{optional}: {group.failed} of {group.trials} trial(s) failed."


def _regressions(
    current: IterationResult, best: IterationResult | None, withheld: frozenset[str]
) -> str:
    """Block [5] — the most actionable line in the message.

    Derived from history but a fact about *now*, so it does not live in
    the ledger. Measured against the incumbent, because the incumbent is
    what the next proposal will be built from.
    """
    if best is None or best is current:
        return ""
    broke = [name for name in _regressed(current, best) if name not in withheld]
    if not broke:
        return ""
    return (
        f"{_RULE}\nREGRESSION WATCH\n{_RULE}\n"
        "These criteria stood higher under the incumbent prompt than under "
        f"your last change: {', '.join(broke)}. Your last edit is the likely "
        "cause; address it or withdraw it."
    )


def _instruction(incumbent: IterationResult, target_key: str) -> str:
    """Block [6] — last, where attention is strongest and caching cannot reach."""
    return (
        f"{_RULE}\nTHE PROMPT TO IMPROVE\n{_RULE}\n"
        "This is the incumbent — the best prompt measured so far, which is "
        "what your edits apply to (not necessarily the one measured most "
        "recently):\n\n"
        f"{incumbent.config.get(target_key, '')}\n\n"
        "Propose few, separable edits addressing the evidence above, and "
        "return the whole revised prompt with them applied. Reply with a "
        "single JSON object and nothing else."
    )


def _regressed(result: IterationResult, reference: IterationResult) -> list[str]:
    """Criteria whose observed rate fell from ``reference`` to ``result``."""
    rates = {e.name: e.rate for e in reference.evidence}
    return [e.name for e in result.evidence if e.name in rates and e.rate < rates[e.name]]


def _outcome(result: IterationResult) -> str:
    return f"score {result.score:.2f} ({result.passes} of {result.samples} samples passed)"


def _rate(criterion: CriterionEvidence) -> str:
    text = f"{criterion.passed} of {criterion.trials} trial(s) held"
    if criterion.lower_bound is not None:
        text += (
            f"; on this many samples the evidence supports no more than "
            f"{criterion.lower_bound:.2f} as a floor"
        )
    return text
