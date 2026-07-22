"""The optimization record: an Optimize experiment's full iteration history.

Each iteration carries a shared :class:`~baseltest.observation.RunObservation`
— the same statistics, cost, gated latency, and result projection an explore
configuration produces — extended with the iteration index, the full
configuration it ran under, and the score the run's scorer assigned.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from baseltest.engine import RunResult
from baseltest.observation import RunObservation

_WIRE_SCORER_NAMES = {"pass-rate": "observed-pass-rate"}


class Objective(StrEnum):
    """The direction an optimization drives its scorer."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class Termination(StrEnum):
    """Why an optimization run stopped."""

    MAX_ITERATIONS = "max-iterations"
    NO_IMPROVEMENT_WINDOW = "no-improvement-window"
    STEPPER_STOPPED = "stepper-stopped"
    DEFECT = "defect"


def wire_scorer_name(registered_name: str) -> str:
    """The scorer's interchange wire name.

    The family's canonical interchange vocabulary names the built-in
    scorer ``observed-pass-rate`` (the registered additive ``scorer``
    field of ``mavai-optimize-1``); baseltest's authoring surface
    registers the same scorer as ``pass-rate``. User-registered scorers
    travel under their registered name verbatim — it is their domain
    name.
    """
    return _WIRE_SCORER_NAMES.get(registered_name, registered_name)


@dataclass(frozen=True, slots=True)
class IterationCapture:
    """One completed iteration: its configuration, score, and observation.

    Attributes:
        index: Zero-based iteration index.
        factors: The full resolved configuration this iteration ran under.
        score: The scoring function's value, in objective units.
        observation: The iteration's descriptive result — the shared
            per-configuration run observation an explore run also records.
    """

    index: int
    factors: tuple[tuple[str, Any], ...]
    score: float
    observation: RunObservation

    @staticmethod
    def from_run_result(
        index: int, result: RunResult, factors: Mapping[str, Any], score: float
    ) -> "IterationCapture":
        """Build one iteration's capture from its completed run."""
        return IterationCapture(
            index=index,
            factors=tuple(factors.items()),
            score=score,
            observation=RunObservation.from_run_result(result, configuration=factors),
        )


@dataclass(frozen=True, slots=True)
class OptimizationRecord:
    """Everything one optimize run's artefact states.

    Attributes:
        contract_id: The optimized contract's identity.
        experiment_id: The run's name — the ``optimizations:`` entry's id.
        objective: ``MAXIMIZE`` or ``MINIMIZE``.
        scorer: The scoring function's interchange wire name — what the
            per-iteration ``score`` measures (see
            :func:`wire_scorer_name`).
        generated_at: When the run finished, UTC.
        iterations: The full history, in execution order — never elided
            or truncated; the history is the artefact.
        best_index: Index of the selected optimum in ``iterations``.
        termination: Why the run stopped — a :class:`Termination`.
        stepper: The stepper's identity and configuration, recorded as
            mutator provenance (an emitter-specific block the schema's
            additive-evolution rule permits).
    """

    contract_id: str
    experiment_id: str
    objective: Objective
    scorer: str
    generated_at: datetime
    iterations: tuple[IterationCapture, ...]
    best_index: int
    termination: Termination
    stepper: tuple[tuple[str, Any], ...] = ()

    @property
    def best(self) -> IterationCapture:
        """The selected optimum's iteration."""
        return self.iterations[self.best_index]
