"""The optimization writer: the family's ``mavai-optimize-1`` schema, one file per run.

Emission is deterministic — the same fixed key order and scalar rendering
as the exploration writer, whose observation blocks each iteration reuses
— so two runs of one optimization diff cleanly. The filename is the run's
id (``optimizations/{contract}/{id}.yaml``); re-running an optimization
refreshes its file in place.
"""

from pathlib import Path

# The family emitters share one deterministic scalar rendering (JSON-quoted
# strings are valid YAML flow scalars, numbers keep their native YAML type);
# the per-iteration observation blocks are the exploration artefact's, reused.
from baseltest.engine.artefact import factor_lines, quote, scalar
from baseltest.exploration import observation_lines

from .record import OptimizationRecord

SCHEMA_VERSION = "mavai-optimize-1"


# mavai-ref: JVI-FJK9SN9 — do not remove (resolves in mavai-orchestrator)
def render_optimization(record: OptimizationRecord) -> str:
    """Serialise one optimize run to the family schema, deterministically.

    The ``convergence`` block is derived from the recorded best iteration,
    so ``bestScore`` and ``bestFactors`` are internally consistent with
    the ``iterations`` entry ``bestIteration`` names by construction — the
    schema-specific binding obligation.

    Raises:
        ValueError: On a record with no iterations — an optimize run
            always executes iteration 0, and the schema binds the history.
    """
    if not record.iterations:
        raise ValueError("an optimization record carries at least one iteration")
    if not 0 <= record.best_index < len(record.iterations):
        raise ValueError(
            f"best iteration {record.best_index} is not in the recorded history "
            f"of {len(record.iterations)}"
        )
    lines = [
        f"schemaVersion: {quote(SCHEMA_VERSION)}",
        f"serviceContractId: {quote(record.contract_id)}",
        f"experimentId: {quote(record.experiment_id)}",
        f"objective: {quote(record.objective.upper())}",
        # What the score measures — the family's registered additive
        # field, so the shared report can label the score column.
        f"scorer: {quote(record.scorer)}",
        f"generatedAt: {quote(record.generated_at.isoformat())}",
    ]
    if record.stepper:
        # Mutator provenance — an emitter-specific block the schema's
        # additive-evolution rule permits.
        lines.append("stepper:")
        for key, value in record.stepper:
            lines.append(f"  {quote(key)}: {scalar(value)}")
    lines.append(f"termination: {quote(record.termination)}")
    lines.append("iterations:")
    for iteration in record.iterations:
        lines.append(f"  - iteration: {iteration.index}")
        # The schema binds the factors block on every iteration; a
        # zero-parameter configuration renders as the empty mapping.
        lines.extend(factor_lines(iteration.factors, indent="    ") or ["    factors: {}"])
        lines.append(f"    score: {scalar(iteration.score)}")
        lines.extend(observation_lines(iteration.observation, indent="    "))
    best = record.best
    lines.extend(
        [
            "convergence:",
            f"  totalIterations: {len(record.iterations)}",
            f"  bestIteration: {best.index}",
            f"  bestScore: {scalar(best.score)}",
        ]
    )
    if best.factors:
        lines.append("  bestFactors:")
        for key, value in best.factors:
            lines.append(f"    {quote(key)}: {scalar(value)}")
    else:
        lines.append("  bestFactors: {}")
    return "\n".join(lines) + "\n"


def write_optimization(record: OptimizationRecord, directory: Path) -> Path:
    """Write one run's artefact to ``directory/{contract}/{experiment id}.yaml``.

    Returns the written path. The filename is the run's id, so re-running
    the same optimization refreshes its file in place.
    """
    target = directory / record.contract_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{record.experiment_id}.yaml"
    path.write_text(render_optimization(record), encoding="utf-8")
    return path
