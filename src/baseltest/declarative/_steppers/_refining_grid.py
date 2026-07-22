"""The ``refining-grid`` built-in stepper: noise-aware coarse-to-fine search.

Whole grids evaluated before any decision, evidence pooled per value across
revisits, interval-based elimination (never a single observed decline), and
independent confirmation epochs before the winner is selected. Its finite-state
machine lives in a typed :class:`_RefiningGridState`; its selection provenance
rides out on the stopping :class:`StepProposal`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL, wilson_interval

from .._errors import ContractConfigurationError
from ._context import OptimizeContext
from ._contract import Phase, StepFunction, StepProposal
from ._numeric import _NUMERIC_TOLERANCE, _grid_values, _numeric


@dataclass(frozen=True, slots=True)
class _Standing:
    """One candidate value's pooled evidence and its uncertainty interval."""

    value: float
    passes: int
    trials: int
    rate: float
    low: float
    high: float


@dataclass(slots=True)
class _RefiningGridState:
    """The refining-grid search's mutable finite-state machine.

    ``phase`` walks START → GRID → CONFIRM → DONE; ``pending`` is the values
    scheduled for measurement in order; ``provenance`` is filled once, at the
    stop, and carried out on the final proposal.
    """

    phase: Phase
    step: float
    pending: list[float] = field(default_factory=list)
    candidates: tuple[float, ...] = ()
    finalists: tuple[float, ...] = ()
    reason: str | None = None
    provenance: Mapping[str, object] | None = None


def _refining_grid(
    key: str,
    lo: float,
    hi: float,
    step: float,
    min_step: float,
    confidence: float = DEFAULT_CONFIDENCE_LEVEL,
    min_improvement: float = 0.02,
    confirmation_epochs: int = 2,
    prefer: str = "low",
) -> StepFunction:
    """Noise-aware, coarse-to-fine grid search over one numeric key.

    Evaluates every value in the current grid, pools the evidence per
    value across *all* visits (a stochastic score is noisy; revisiting a
    value is how the search buys confidence), then narrows to the
    leader's surrounding grid points at half the step and repeats. No
    single observed decline eliminates anything — a candidate drops out
    only when its uncertainty interval can no longer carry a meaningful
    advantage over the leader's. Refinement stops at ``min-step`` or when
    no plausible challenger remains; the finalists are then re-evaluated
    in independent confirmation epochs and the winner selected on pooled
    evidence, with a practical tie resolved by the ``prefer`` policy
    (lower value by default). The selection, finalist standings, and
    stopping reason are recorded on the stopping proposal's provenance,
    landing in the artefact's ``stepper:`` block.
    """
    if not lo < hi:
        raise ContractConfigurationError(
            f"stepper 'refining-grid': `lo:` ({lo}) must be below `hi:` ({hi})"
        )
    if step <= 0 or min_step <= 0 or min_step > step:
        raise ContractConfigurationError(
            "stepper 'refining-grid': `step:` and `min-step:` must be positive, "
            f"with `min-step:` at most `step:` — got step {step}, min-step {min_step}"
        )
    if not 0 < confidence < 1:
        raise ContractConfigurationError(
            f"stepper 'refining-grid': `confidence:` must be between 0 and 1, got {confidence}"
        )
    if min_improvement < 0:
        raise ContractConfigurationError(
            f"stepper 'refining-grid': `min-improvement:` must be at least 0, got {min_improvement}"
        )
    if confirmation_epochs < 0:
        raise ContractConfigurationError(
            "stepper 'refining-grid': `confirmation-epochs:` must be at least 0, "
            f"got {confirmation_epochs}"
        )
    if prefer not in ("low", "high"):
        raise ContractConfigurationError(
            f"stepper 'refining-grid': `prefer:` must be 'low' or 'high', got {prefer!r}"
        )

    state = _RefiningGridState(phase=Phase.START, step=step)

    def pooled(ctx: OptimizeContext) -> dict[float, tuple[int, int]]:
        """Per-value evidence pooled across every visit in the history."""
        evidence: dict[float, tuple[int, int]] = {}
        for entry in ctx.history:
            value = round(_numeric(entry.config.get(key), "refining-grid", key), 12)
            passes, trials = evidence.get(value, (0, 0))
            evidence[value] = (passes + entry.passes, trials + entry.samples)
        return evidence

    def standings(values: tuple[float, ...], ctx: OptimizeContext) -> list[_Standing]:
        # Pragmatic uncertainty model, deliberately outside the Statistical
        # Companion's scope: per-candidate pooled counts with two-sided
        # Wilson intervals (reusing the conformance-locked implementation),
        # compared unpaired. This is a budget-bounded search policy, not a
        # calibrated hypothesis test — it decides where to look next, never
        # a verdict.
        evidence = pooled(ctx)
        rows = []
        for value in values:
            passes, trials = evidence.get(value, (0, 0))
            if trials == 0:
                continue
            interval = wilson_interval(passes, trials, confidence)
            rows.append(
                _Standing(
                    value=value,
                    passes=passes,
                    trials=trials,
                    rate=passes / trials,
                    low=interval.lower_bound,
                    high=interval.upper_bound,
                )
            )
        return rows

    def better(a: _Standing, b: _Standing) -> bool:
        """Whether ``a`` outranks ``b``: higher rate, ties by the prefer policy."""
        if a.rate != b.rate:
            return a.rate > b.rate
        return a.value < b.value if prefer == "low" else a.value > b.value

    def leader_and_challengers(
        rows: list[_Standing],
    ) -> tuple[_Standing, list[_Standing]]:
        leader = rows[0]
        for row in rows[1:]:
            if better(row, leader):
                leader = row
        # A challenger stays plausible while its optimistic bound beats the
        # leader's pessimistic bound by more than the meaningful margin —
        # one observed decline never eliminates anyone; intervals do.
        challengers = [
            row for row in rows if row is not leader and row.high - leader.low > min_improvement
        ]
        return leader, challengers

    def schedule(values: tuple[float, ...]) -> None:
        state.candidates = values
        state.pending = list(values)

    def finish(winner: _Standing, rows: list[_Standing], confirmed: bool) -> None:
        state.phase = Phase.DONE
        rendered = "; ".join(
            f"{row.value:g} (rate {row.rate:.4f}, {row.passes}/{row.trials}, "
            f"interval {row.low:.4f}-{row.high:.4f})"
            for row in sorted(rows, key=lambda r: r.value)
        )
        state.provenance = {
            "selectedValue": winner.value,
            "selectedRate": round(winner.rate, 6),
            "selectedIntervalLow": round(winner.low, 6),
            "selectedIntervalHigh": round(winner.high, 6),
            "stoppingReason": str(state.reason),
            "confirmed": confirmed,
            "finalists": rendered,
        }

    def decide_after_grid(ctx: OptimizeContext) -> None:
        rows = standings(state.candidates, ctx)
        leader, challengers = leader_and_challengers(rows)
        half = state.step / 2
        if challengers and half >= min_step - _NUMERIC_TOLERANCE:
            # Refine: the leader's surrounding grid points at half the step.
            state.step = half
            schedule(
                _grid_values(
                    max(lo, leader.value - 2 * half), min(hi, leader.value + 2 * half), half
                )
            )
            return
        state.reason = "min-step" if challengers else "no-plausible-challenger"
        strongest = None
        for row in challengers:
            if strongest is None or better(row, strongest):
                strongest = row
        if strongest is None or confirmation_epochs == 0:
            finalists = [leader] + ([strongest] if strongest is not None else [])
            state.finalists = tuple(row.value for row in finalists)
            finish(leader, finalists, confirmed=False)
            return
        state.phase = Phase.CONFIRM
        state.finalists = (leader.value, strongest.value)
        state.pending = list(state.finalists) * confirmation_epochs

    def decide_after_confirmation(ctx: OptimizeContext) -> None:
        rows = standings(state.finalists, ctx)
        leader, _ = leader_and_challengers(rows)
        runner_up = next((row for row in rows if row is not leader), None)
        # A practical tie — a difference below the meaningful margin — is
        # resolved by the tie-break policy, not by whichever rate is ahead.
        if (
            runner_up is not None
            and abs(leader.rate - runner_up.rate) <= min_improvement
            and (runner_up.value < leader.value) == (prefer == "low")
        ):
            leader = runner_up
        finish(leader, rows, confirmed=True)

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> StepProposal:
        _numeric(current.get(key), "refining-grid", key)  # fail fast on a non-numeric key
        if state.phase is Phase.START:
            state.phase = Phase.GRID
            schedule(_grid_values(lo, hi, state.step))
        while not state.pending and state.phase in (Phase.GRID, Phase.CONFIRM):
            if state.phase is Phase.GRID:
                decide_after_grid(ctx)
            else:
                decide_after_confirmation(ctx)
        if state.phase is Phase.DONE:
            return StepProposal(config=None, provenance=state.provenance)
        return StepProposal(config={**current, key: state.pending.pop(0)})

    return advance
