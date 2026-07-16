"""The optimization record: an Optimize experiment's full iteration history.

Each iteration's descriptive observation shares its shape with the
exploration record — the same statistics, cost, gated latency, and result
projection — extended with the iteration index, the full configuration it
ran under, and the score the run's scorer assigned.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from baseltest.engine import RunResult
from baseltest.exploration import ExplorationRecord


@dataclass(frozen=True, slots=True)
class IterationCapture:
    """One completed iteration: its configuration, score, and observation.

    Attributes:
        index: Zero-based iteration index.
        factors: The full resolved configuration this iteration ran under.
        score: The scoring function's value, in objective units.
        observation: The iteration's descriptive result — the same
            per-configuration observation shape the exploration artefact
            records.
    """

    index: int
    factors: tuple[tuple[str, Any], ...]
    score: float
    observation: ExplorationRecord

    @staticmethod
    def from_run_result(
        index: int, result: RunResult, factors: dict[str, Any], score: float
    ) -> "IterationCapture":
        """Build one iteration's capture from its completed run."""
        return IterationCapture(
            index=index,
            factors=tuple(factors.items()),
            score=score,
            observation=ExplorationRecord.from_run_result(result, configuration=factors),
        )


@dataclass(frozen=True, slots=True)
class OptimizationRecord:
    """Everything one optimize run's artefact states.

    Attributes:
        contract_id: The optimized contract's identity.
        experiment_id: The run's name — the ``optimizations:`` entry's id.
        objective: ``MAXIMIZE`` or ``MINIMIZE``.
        generated_at: When the run finished, UTC.
        iterations: The full history, in execution order — never elided
            or truncated; the history is the artefact.
        best_index: Index of the selected optimum in ``iterations``.
        termination: Why the run stopped — ``max-iterations``,
            ``no-improvement-window``, or ``stepper-stopped``.
        stepper: The stepper's identity and configuration, recorded as
            mutator provenance (an emitter-specific block the schema's
            additive-evolution rule permits).
    """

    contract_id: str
    experiment_id: str
    objective: str
    generated_at: datetime
    iterations: tuple[IterationCapture, ...]
    best_index: int
    termination: str
    stepper: tuple[tuple[str, Any], ...] = ()

    @property
    def best(self) -> IterationCapture:
        """The selected optimum's iteration."""
        return self.iterations[self.best_index]
