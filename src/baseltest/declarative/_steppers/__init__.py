"""Steppers and scorers: the Optimize experiment's author-suppliable pieces.

A **stepper** proposes the next configuration to try: a plain function
``step(current, ctx)`` receiving the whole current configuration mapping
and the run's context (history, best so far, remaining budget), returning a
:class:`StepProposal` — the whole next configuration mapping with optional
provenance — or ``None``/a bare mapping to propose or stop without any. It is
registered as a **factory**, mirroring the binding-factory form: the factory's
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

This package is a thin facade over the concern-split submodules: the
iteration context (`_context`), the stepper/scorer contract and config
binding (`_contract`), the numeric helpers (`_numeric`), the three built-in
steppers (`_linear_sweep`, `_refining_grid`, `_prompt_engineer`), and the
built-in seed (`_builtins`).
"""

from ._builtins import builtin_scorers, builtin_stepper_registrations
from ._context import (
    FailureDetail,
    FailureExemplar,
    IterationResult,
    IterationSummary,
    LatencySummary,
    OptimizeContext,
)
from ._contract import (
    Phase,
    ScorerFunction,
    StepFunction,
    StepperRegistration,
    StepProposal,
    bind_stepper_config,
    vet_stepper_factory,
)

__all__ = [
    "FailureDetail",
    "FailureExemplar",
    "IterationResult",
    "IterationSummary",
    "LatencySummary",
    "OptimizeContext",
    "Phase",
    "ScorerFunction",
    "StepFunction",
    "StepProposal",
    "StepperRegistration",
    "bind_stepper_config",
    "builtin_scorers",
    "builtin_stepper_registrations",
    "vet_stepper_factory",
]
