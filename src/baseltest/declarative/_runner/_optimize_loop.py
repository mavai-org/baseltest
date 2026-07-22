"""One optimize entry's loop: iterate, score, track the best, persist.

``_drive_optimization`` runs a single ``optimizations:`` entry's settled
loop and contains a mid-run defect to that entry; the helpers shape one
iteration's aggregate, apply one stepper proposal, and build the artefact's
provenance blocks.
"""

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baseltest.engine import DefectDiagnosisError, RunResult, execute, latency_block
from baseltest.optimization import (
    IterationCapture,
    Objective,
    OptimizationRecord,
    Termination,
    wire_scorer_name,
    write_optimization,
)
from baseltest.reporting import render_optimization_run

from .._errors import ContractConfigurationError
from .._instantiate import instantiate_optimize_point
from .._optimize import OptimizationDeclaration
from .._parser import ContractDeclaration
from .._registry import Registry
from .._services import ServiceDefinition
from .._services import _resolved_point as _configuration_identity
from .._steppers import (
    FailureDetail,
    FailureExemplar,
    IterationResult,
    IterationSummary,
    LatencySummary,
    OptimizeContext,
    StepProposal,
)
from ._shared import _tty_progress


@dataclass(frozen=True, slots=True)
class OptimizationOutcome:
    """One executed optimize run: its record and its artefact path.

    ``record`` and ``path`` are ``None`` only when a defect stopped the run
    before its first iteration produced a scored data point — there is then
    no history to persist. ``defect`` carries the diagnosis when a defect
    stopped the search (whether or not any iteration completed first).
    """

    run_id: str
    record: OptimizationRecord | None
    path: Path | None
    defect: str | None = None


def _drive_optimization(
    declaration: ContractDeclaration,
    definition: ServiceDefinition,
    entry: OptimizationDeclaration,
    samples: int,
    optimizations_dir: Path,
    emit: bool,
    registry: Registry,
) -> OptimizationOutcome:
    """One entry's full loop: iterate, score, track the best, persist.

    A defect (a non-``TransformError`` exception escaping a transform or
    postcondition) that escapes an iteration's sampling cannot yield a score
    — a defected iteration is not a data point. It is contained here: the
    search stops with a ``defect`` termination, the defected iteration is
    *not* appended to the history (recording it as a scored iteration would
    be dishonest), and the best is selected among the iterations that did
    complete. This keeps the defect from forfeiting the whole entry's paid
    spend and, under ``--all``, keeps it from killing sibling entries — an
    entry whose very first iteration defects yields no persistable history,
    so it returns an aborted outcome with no artefact rather than an empty
    one.
    """
    history: list[IterationResult] = []
    captures: list[IterationCapture] = []
    best: IterationResult | None = None
    best_index = 0
    plateau = 0
    termination = Termination.MAX_ITERATIONS
    defect_diagnosis: str | None = None
    parameters = entry.parameters
    step_provenance: Mapping[str, object] | None = None
    visited: set[tuple[Any, ...]] = set()
    for index in range(entry.max_iterations):
        visited.add(_configuration_identity(definition.type, parameters))
        point = instantiate_optimize_point(declaration, definition, parameters, samples, registry)
        label = f"{entry.run_id} iteration {index}"
        try:
            result = execute(
                point.contract,
                point.plan,
                on_sample=_tty_progress(label) if emit else None,
                record_samples=True,  # projections and exemplars are the payload
            )
        except DefectDiagnosisError as defect:
            defect_diagnosis = str(defect)
            termination = Termination.DEFECT
            if emit:
                print(f"note: {label} aborted — {defect}", file=sys.stderr)
            break
        summary = _iteration_summary(result)
        score = float(entry.score(summary))
        iteration_result = IterationResult(
            config=dict(point.configuration), score=score, summary=summary
        )
        history.append(iteration_result)
        captures.append(IterationCapture.from_run_result(index, result, point.configuration, score))
        if best is None or _improved(score, best.score, entry.objective):
            best = iteration_result
            best_index = index
            plateau = 0
        else:
            plateau += 1
            if entry.no_improvement_window is not None and plateau >= entry.no_improvement_window:
                termination = Termination.NO_IMPROVEMENT_WINDOW
                break
        if index + 1 == entry.max_iterations:
            break  # the cap is reached; no next configuration to propose
        context = OptimizeContext(
            history=tuple(history),
            best=best,
            iteration=index + 1,
            iterations_remaining=entry.max_iterations - (index + 1),
        )
        next_parameters, proposal_provenance = _next_parameters(
            entry, definition, context, iteration_result.config, index + 1
        )
        if proposal_provenance is not None:
            step_provenance = proposal_provenance
        if next_parameters is None:
            termination = Termination.STEPPER_STOPPED
            break
        if emit and _configuration_identity(definition.type, next_parameters) in visited:
            # Deliberate, not a defect: under a stochastic service a single
            # visit's score is noisy, and repeated visits pool into
            # stronger evidence — say so instead of looking stuck.
            print(
                f"note: iteration {index + 1} re-measures a configuration this run "
                "has already visited — repeated measurements accumulate evidence "
                "against the noise in any single visit"
            )
        parameters = next_parameters

    if not captures:
        # A defect stopped the search before any iteration produced a scored
        # data point: there is no history to persist. Report the aborted
        # entry (no artefact) and let sibling entries run.
        if emit:
            print(
                f"note: optimization {entry.run_id!r} produced no scored iteration "
                "— aborted by a defect before iteration 0 completed; no artefact written",
                file=sys.stderr,
            )
        return OptimizationOutcome(
            run_id=entry.run_id, record=None, path=None, defect=defect_diagnosis
        )

    record = OptimizationRecord(
        contract_id=declaration.contract,
        experiment_id=entry.run_id,
        objective=entry.objective,
        scorer=wire_scorer_name(entry.scorer_name),
        generated_at=captures[-1].observation.generated_at,
        iterations=tuple(captures),
        best_index=best_index,
        termination=termination,
        stepper=_stepper_block(entry, step_provenance),
    )
    artefact = write_optimization(record, optimizations_dir)
    if emit:
        print(
            render_optimization_run(
                declaration.contract,
                entry.run_id,
                samples,
                [
                    (c.index, c.score, c.observation.successes, c.observation.samples_executed)
                    for c in captures
                ],
                termination,
                best_index,
                dict(record.best.factors),
                artefact.as_posix(),
            )
        )
    return OptimizationOutcome(
        run_id=entry.run_id, record=record, path=artefact, defect=defect_diagnosis
    )


def _iteration_summary(result: RunResult) -> IterationSummary:
    """One iteration's aggregate, in the shape scorers and steppers consume."""
    exemplars: dict[str, list[FailureExemplar]] = {}
    for sample in result.samples:
        for name, reason in sample.failure_reasons:
            exemplars.setdefault(name, []).append(
                FailureExemplar(input=result.plan.inputs[sample.input_index], reason=reason)
            )
    failures: dict[str, FailureDetail] = {}
    for criterion_result in result.criterion_results:
        tally = criterion_result.tally
        failed = tally.trials - tally.successes
        if failed:
            failures[criterion_result.name] = FailureDetail(
                count=failed, exemplars=tuple(exemplars.get(criterion_result.name, ()))
            )
    block = latency_block(result.samples)
    latency = None
    if block is not None:
        stated = dict(block.percentiles)
        latency = LatencySummary(
            contributing_samples=block.contributing_samples,
            total_samples=block.total_samples,
            p50_ms=stated.get("p50Ms"),
            p90_ms=stated.get("p90Ms"),
            p95_ms=stated.get("p95Ms"),
            p99_ms=stated.get("p99Ms"),
        )
    return IterationSummary(
        passes=result.overall_successes,
        samples=result.plan.samples,
        failures_by_criterion=failures,
        latency=latency,
    )


def _improved(score: float, best: float, objective: Objective) -> bool:
    return score > best if objective is Objective.MAXIMIZE else score < best


def _stepper_block(
    entry: OptimizationDeclaration, provenance: Mapping[str, object] | None
) -> tuple[tuple[str, object], ...]:
    """The artefact's mutator-provenance block: name, config, runtime residue.

    ``provenance`` is the last residue a proposal carried this run — the
    refining-grid's selection, the prompt-engineer's meta identity — or
    ``None`` for a stepper that carries none.
    """
    block: list[tuple[str, object]] = [("name", entry.stepper_name)]
    block.extend((key.replace("_", "-"), value) for key, value in entry.stepper_config.items())
    if provenance is not None:
        block.extend(sorted(provenance.items()))
    return tuple(block)


def _next_parameters(
    entry: OptimizationDeclaration,
    definition: ServiceDefinition,
    context: OptimizeContext,
    configuration: dict[str, Any],
    iteration: int,
) -> tuple[Any | None, Mapping[str, object] | None]:
    """One stepper call, its proposal validated into the next parameters.

    Returns the next parameters (``None`` when the stepper stopped the
    search) and the proposal's provenance (``None`` when it carried none).
    A stepper may return a :class:`StepProposal` — the next configuration
    mapping (or ``None`` to stop) with optional provenance — or, plainly, a
    bare configuration mapping or ``None`` with no provenance. Any
    configuration the service type accepts is a legitimate proposal —
    including one this run has already measured: a stochastic score is
    noisy, and re-measuring a configuration pools into stronger evidence
    (the caller notes a revisit on the console rather than refusing it).

    Raises:
        ContractConfigurationError: The proposal is not a configuration
            mapping, or does not fit the service type.
    """
    where = (
        f"optimization {entry.run_id!r}: iteration {iteration} configuration "
        f"(from stepper {entry.stepper_name!r})"
    )
    outcome = entry.step(dict(configuration), context)
    if isinstance(outcome, StepProposal):
        config, provenance = outcome.config, outcome.provenance
    else:
        config, provenance = outcome, None
    if config is None:
        return None, provenance
    if not isinstance(config, dict):
        raise ContractConfigurationError(
            f"{where}: the stepper returned {type(config).__name__}, not a "
            "configuration mapping — a stepper returns the whole next "
            "configuration, or None to stop"
        )
    return definition.type.parse(definition.name, config, where), provenance
