"""Steppers and scorers: the Optimize experiment's author-suppliable pieces.

A **stepper** proposes the next configuration to try: a plain function
``step(current, ctx)`` receiving the whole current configuration mapping
and the run's context (history, best so far, remaining budget), returning
a whole configuration mapping — or ``None`` to stop. It is registered as
a **factory**, mirroring the binding-factory form: the factory's
snake_case parameters are the ``stepper-config:`` schema, and a stateful
search algorithm keeps its state in the factory's closure scope — the
framework carries no stepper state of its own.

A **scorer** turns one iteration's aggregate result into the number the
run drives: ``fn(summary) -> float``. The default (``pass-rate``) is the
iteration's observed overall pass rate.

Built-ins registered here:

- ``prompt-engineer`` — a meta-LLM prompt tuner: each iteration sends the
  current prompt, its score, and the per-criterion failure breakdown with
  exemplars to a meta model and treats the response as the next prompt.
- ``linear-sweep`` — walks one numeric key in fixed increments; plateau
  detection (``no-improvement-window``) is what makes this an
  optimisation rather than an exploration grid respelled.
- ``refining-grid`` — noise-aware, coarse-to-fine grid search over one
  numeric key: whole grids evaluated before any decision, evidence
  pooled per value across revisits, interval-based elimination (never a
  single observed decline), and independent confirmation epochs before
  the winner is selected.
- ``pass-rate`` — the default scorer.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL, wilson_interval

from ._errors import ContractConfigurationError
from ._signatures import (
    SCALAR_TYPES,
    kebab,
    rendered_signature,
    snake,
    value_fits,
)

StepFunction = Callable[[dict[str, Any], "OptimizeContext"], dict[str, Any] | None]
ScorerFunction = Callable[["IterationSummary"], float]


class Phase(StrEnum):
    """The refining-grid stepper's finite-state machine phase."""

    START = "start"
    GRID = "grid"
    CONFIRM = "confirm"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class FailureExemplar:
    """One failing sample a criterion saw: the driving input and the reason."""

    input: Any
    reason: str


@dataclass(frozen=True, slots=True)
class FailureDetail:
    """One criterion's failures over an iteration: the count and exemplars."""

    count: int
    exemplars: tuple[FailureExemplar, ...] = ()


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """The gated latency percentiles one iteration observed, if any.

    A percentile is ``None`` when too few samples passed to state it —
    the family's minimum-contributing-samples gate, not missing data.
    """

    contributing_samples: int
    total_samples: int
    p50_ms: int | None = None
    p90_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None


@dataclass(frozen=True, slots=True)
class IterationSummary:
    """One iteration's aggregate result — what a scorer consumes.

    Attributes:
        passes: Samples on which every criterion passed.
        samples: Samples executed this iteration.
        failures_by_criterion: Per-criterion failure counts with exemplars,
            criteria that failed nothing omitted.
        latency: The gated latency summary; ``None`` when no sample passed.
    """

    passes: int
    samples: int
    failures_by_criterion: Mapping[str, FailureDetail] = field(default_factory=dict)
    latency: LatencySummary | None = None

    @property
    def pass_rate(self) -> float:
        """The observed overall pass rate; 0.0 with no samples."""
        return self.passes / self.samples if self.samples else 0.0


@dataclass(frozen=True, slots=True)
class IterationResult:
    """One completed iteration, as a stepper's history sees it."""

    config: dict[str, Any]
    score: float
    summary: IterationSummary

    @property
    def passes(self) -> int:
        """Samples on which every criterion passed."""
        return self.summary.passes

    @property
    def samples(self) -> int:
        """Samples executed this iteration."""
        return self.summary.samples

    @property
    def failures_by_criterion(self) -> Mapping[str, FailureDetail]:
        """Per-criterion failure counts with exemplars."""
        return self.summary.failures_by_criterion

    @property
    def latency(self) -> LatencySummary | None:
        """The gated latency summary; ``None`` when no sample passed."""
        return self.summary.latency


@dataclass(frozen=True, slots=True)
class OptimizeContext:
    """The frozen per-iteration view a stepper decides from.

    Attributes:
        history: Every completed iteration, oldest first.
        best: The best iteration so far, objective-aware.
        iteration: The index of the iteration the stepper is about to
            propose.
        iterations_remaining: How many more iterations the run's cap
            allows — the stepper's budget visibility.
    """

    history: tuple[IterationResult, ...]
    best: IterationResult | None
    iteration: int
    iterations_remaining: int


@dataclass(frozen=True, slots=True)
class StepperRegistration:
    """One registered stepper: its factory and its validation residue.

    Attributes:
        name: The registry name ``stepper:`` entries reference.
        factory: Constructs the step function from the entry's
            ``stepper-config:`` (snake_case keyword arguments).
        configuration_keys: Factory parameters whose *values* name keys of
            the optimized service's configuration — validated to exist
            there at load time (e.g. ``target-key``, ``key``).
        builtin: Whether the framework registered it.
    """

    name: str
    factory: Callable[..., StepFunction]
    configuration_keys: tuple[str, ...] = ()
    builtin: bool = False


def vet_stepper_factory(name: str, factory: Callable[..., StepFunction]) -> None:
    """Every stepper factory parameter must be keyword-bindable.

    Stepper-config keys bind by name, so a positional-only or var-positional
    parameter can never be reached — refused at registration time.
    """
    for parameter in inspect.signature(factory).parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            raise ContractConfigurationError(
                f"stepper {name!r}: parameter {parameter.name!r} is not "
                "keyword-bindable — stepper-config keys bind by name, so factory "
                "parameters must be ordinary or keyword-only"
            )


def bind_stepper_config(
    service: str,
    where: str,
    registration: StepperRegistration,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one entry's ``stepper-config:`` mapping to its factory's signature.

    The same rule as a binding factory's configuration: kebab-case keys
    map to snake_case parameters, parameters with defaults are the
    optional keys, scalar annotations are checked where declared, and a
    mapping that does not fit is refused with the signature in the
    message. Returns the keyword arguments ready for the factory.
    """
    factory = registration.factory
    rendered = rendered_signature(registration.name, factory)
    parameters = inspect.signature(factory).parameters
    named = {p.name for p in parameters.values() if p.kind is not inspect.Parameter.VAR_KEYWORD}
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    required = {
        p.name
        for p in parameters.values()
        if p.default is inspect.Parameter.empty and p.kind is not inspect.Parameter.VAR_KEYWORD
    }
    for key, value in raw.items():
        key = str(key)
        if not isinstance(value, SCALAR_TYPES):
            raise ContractConfigurationError(
                f"service {service!r}: {where}: `{key}:` must be a scalar "
                f"(string, number, or boolean), got {type(value).__name__}"
            )
        if snake(key) not in named and not accepts_any:
            accepted = ", ".join(kebab(p) for p in sorted(named)) or "(none)"
            raise ContractConfigurationError(
                f"service {service!r}: {where} has unknown key `{key}:` — the stepper "
                f"{registration.name!r} accepts: {accepted}; its factory's signature "
                f"is {rendered}"
            )
        annotation = parameters[snake(key)].annotation if snake(key) in named else None
        if annotation in SCALAR_TYPES and not value_fits(value, annotation):
            raise ContractConfigurationError(
                f"service {service!r}: {where}: `{key}:` expects "
                f"{annotation.__name__}, got {type(value).__name__} ({value!r}) — "
                f"the stepper's factory signature is {rendered}"
            )
    missing = sorted(required - {snake(str(key)) for key in raw})
    if missing:
        keys = ", ".join(f"`{kebab(m)}:`" for m in missing)
        raise ContractConfigurationError(
            f"service {service!r}: {where} is missing {keys} — required by the "
            f"stepper {registration.name!r}, whose factory's signature is {rendered}"
        )
    return {snake(str(key)): value for key, value in raw.items()}


# ---------------------------------------------------------------------------
# Built-in scorer
# ---------------------------------------------------------------------------


def _pass_rate(summary: IterationSummary) -> float:
    return summary.pass_rate


# ---------------------------------------------------------------------------
# Built-in steppers
# ---------------------------------------------------------------------------

_NUMERIC_TOLERANCE = 1e-9


def _numeric(value: Any, name: str, key: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ContractConfigurationError(
            f"stepper {name!r}: configuration key {key!r} holds "
            f"{type(value).__name__} ({value!r}), not a number — this stepper "
            "walks a numeric factor"
        )
    return float(value)


def _linear_sweep(key: str, step: float, stop: float) -> StepFunction:
    """Walk ``key`` from its starting value in fixed increments up to ``stop``.

    A fixed grid you want fully characterised is an exploration; what
    makes the sweep an optimisation is the sequential machinery — the
    scorer, best-tracking, and above all plateau stopping that abandons
    the walk as soon as it stops paying.
    """
    if step == 0:
        raise ContractConfigurationError(
            "stepper 'linear-sweep': `step:` must be non-zero — a zero step "
            "re-measures the same configuration forever"
        )

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> dict[str, Any] | None:
        value = _numeric(current[key], "linear-sweep", key)
        proposed = value + step
        past_stop = (
            proposed > stop + _NUMERIC_TOLERANCE
            if step > 0
            else (proposed < stop - _NUMERIC_TOLERANCE)
        )
        if past_stop:
            return None
        return {**current, key: round(proposed, 12)}

    return advance


def _grid_values(lo: float, hi: float, step: float) -> tuple[float, ...]:
    """The grid ``lo, lo+step, …, hi`` (both bounds included), rounded stably."""
    count = int(round((hi - lo) / step))
    values = [round(lo + index * step, 12) for index in range(count + 1)]
    if abs(values[-1] - hi) > _NUMERIC_TOLERANCE:
        values.append(round(hi, 12))
    return tuple(values)


@dataclass(frozen=True, slots=True)
class _Standing:
    """One candidate value's pooled evidence and its uncertainty interval."""

    value: float
    passes: int
    trials: int
    rate: float
    low: float
    high: float


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
    stopping reason are recorded on the step function's provenance
    channel, landing in the artefact's ``stepper:`` block.
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

    state: dict[str, Any] = {
        "phase": Phase.START,  # START → GRID → CONFIRM → DONE
        "pending": [],  # values scheduled for measurement, in order
        "step": step,
        "candidates": (),  # the current round's grid values
        "finalists": (),
        "reason": None,
    }

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
        state["candidates"] = values
        state["pending"] = list(values)

    def finish(winner: _Standing, rows: list[_Standing], confirmed: bool) -> None:
        state["phase"] = Phase.DONE
        rendered = "; ".join(
            f"{row.value:g} (rate {row.rate:.4f}, {row.passes}/{row.trials}, "
            f"interval {row.low:.4f}-{row.high:.4f})"
            for row in sorted(rows, key=lambda r: r.value)
        )
        advance.provenance = {  # type: ignore[attr-defined]
            "selectedValue": winner.value,
            "selectedRate": round(winner.rate, 6),
            "selectedIntervalLow": round(winner.low, 6),
            "selectedIntervalHigh": round(winner.high, 6),
            "stoppingReason": str(state["reason"]),
            "confirmed": confirmed,
            "finalists": rendered,
        }

    def decide_after_grid(ctx: OptimizeContext) -> None:
        rows = standings(state["candidates"], ctx)
        leader, challengers = leader_and_challengers(rows)
        half = state["step"] / 2
        if challengers and half >= min_step - _NUMERIC_TOLERANCE:
            # Refine: the leader's surrounding grid points at half the step.
            state["step"] = half
            schedule(
                _grid_values(
                    max(lo, leader.value - 2 * half), min(hi, leader.value + 2 * half), half
                )
            )
            return
        state["reason"] = "min-step" if challengers else "no-plausible-challenger"
        strongest = None
        for row in challengers:
            if strongest is None or better(row, strongest):
                strongest = row
        if strongest is None or confirmation_epochs == 0:
            finalists = [leader] + ([strongest] if strongest is not None else [])
            state["finalists"] = tuple(row.value for row in finalists)
            finish(leader, finalists, confirmed=False)
            return
        state["phase"] = Phase.CONFIRM
        state["finalists"] = (leader.value, strongest.value)
        state["pending"] = list(state["finalists"]) * confirmation_epochs

    def decide_after_confirmation(ctx: OptimizeContext) -> None:
        rows = standings(state["finalists"], ctx)
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

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> dict[str, Any] | None:
        _numeric(current.get(key), "refining-grid", key)  # fail fast on a non-numeric key
        if state["phase"] is Phase.START:
            state["phase"] = Phase.GRID
            schedule(_grid_values(lo, hi, state["step"]))
        while not state["pending"] and state["phase"] in (Phase.GRID, Phase.CONFIRM):
            if state["phase"] is Phase.GRID:
                decide_after_grid(ctx)
            else:
                decide_after_confirmation(ctx)
        if state["phase"] is Phase.DONE:
            return None
        return {**current, key: state["pending"].pop(0)}

    return advance


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
    silently pinned. The resolved meta identity is recorded on the step
    function's ``provenance`` attribute for the artefact.
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
        from ._providers import build_invoker, resolve_provider
        from ._services import LanguageModelParameters

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

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> dict[str, Any] | None:
        last = ctx.history[-1]
        invoke, meta_provider, meta_model = meta_invoker(current)
        advance.provenance = {  # type: ignore[attr-defined]
            "metaProvider": meta_provider or "openai-compatible",
            "metaModel": meta_model or "(environment default)",
            "metaTemperature": temperature,
        }
        suggestion = invoke(_meta_message(last, target_key, max_exemplars)).strip()
        if not suggestion:
            return None  # a meta model with nothing to propose stops the run
        return {**current, target_key: suggestion}

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


def builtin_stepper_registrations() -> tuple[StepperRegistration, ...]:
    """The framework-shipped steppers every :class:`Registry` starts with."""
    return (
        StepperRegistration(
            name="prompt-engineer",
            factory=_prompt_engineer,
            configuration_keys=("target_key",),
            builtin=True,
        ),
        StepperRegistration(
            name="linear-sweep", factory=_linear_sweep, configuration_keys=("key",), builtin=True
        ),
        StepperRegistration(
            name="refining-grid", factory=_refining_grid, configuration_keys=("key",), builtin=True
        ),
    )


def builtin_scorers() -> dict[str, ScorerFunction]:
    """The framework-shipped scorers every :class:`Registry` starts with."""
    return {"pass-rate": _pass_rate}
