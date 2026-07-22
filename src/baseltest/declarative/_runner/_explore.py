"""The ``explore`` verb: run the contract over every configuration in the grid.

Per configuration this is a measure run in miniature with a descriptive
posture — no thresholds consulted, no verdict rendered, one exploration
artefact per configuration. A runtime defect is contained per configuration;
the remaining configurations run to completion.
"""

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from baseltest.engine import DefectDiagnosisError, RunResult, execute
from baseltest.exploration import ExplorationRecord, exploration_stem, write_exploration
from baseltest.reporting import render_explorations, render_run_plan

from .._instantiate import instantiate_explore
from .._parser import load_contract
from .._registrations import discover_registrations
from .._registry import Bindings
from .._services import discover_services
from ._shared import DEFAULT_EXPLORATIONS_DIR, _tty_progress


@dataclass(frozen=True, slots=True)
class ConfigurationExploration:
    """One explored configuration: its factors, its run result, its artefact."""

    factors: dict[str, object]
    result: RunResult
    path: Path


@dataclass(frozen=True, slots=True)
class AbortedConfiguration:
    """One configuration a defect stopped: its factors and the diagnosis.

    A defect is a bug in the testing machinery — not a countable outcome and
    not a sample. It stops *its* configuration with an actionable diagnosis
    instead of forfeiting the whole grid's paid spend; the remaining
    configurations run to completion.
    """

    factors: dict[str, object]
    diagnosis: str


@dataclass(frozen=True, slots=True)
class ExplorationRun:
    """An explore run's outcome: the configurations that completed, and any a
    defect contained.

    Iterating or indexing an ``ExplorationRun`` yields the *completed*
    configurations (baseline first), so the run reads as the sequence of
    artefacts it produced. ``aborted`` carries the configurations a defect
    stopped, each with its diagnosis: a partial run is a reported outcome,
    never a silent truncation.
    """

    completed: tuple[ConfigurationExploration, ...]
    aborted: tuple[AbortedConfiguration, ...] = ()

    def __iter__(self) -> "Iterator[ConfigurationExploration]":
        return iter(self.completed)

    def __len__(self) -> int:
        return len(self.completed)

    def __getitem__(self, index: int) -> ConfigurationExploration:
        return self.completed[index]


# mavai-ref: JVI-HGF78G* — do not remove (resolves in mavai-orchestrator)
def explore(
    path: str | Path,
    *,
    samples_per_config: int | None = None,
    explorations_dir: str | Path = DEFAULT_EXPLORATIONS_DIR,
    emit: bool = True,
    bindings: Bindings | None = None,
) -> ExplorationRun:
    """Run the contract's inputs and criteria over every configuration in the grid.

    Per configuration this is a measure run in miniature — the same
    sampling loop, ``samples_per_config`` samples (default: a deliberately
    small count; triage is small by design) — with a descriptive posture:
    no thresholds are consulted, no verdict is rendered, and one
    exploration artefact per configuration is persisted. The core use is
    diffing two configurations' artefacts.

    Args:
        path: The contract file.
        samples_per_config: Samples per grid point; omitted, the small
            default applies.
        explorations_dir: The artefact directory; one subdirectory per
            contract, one file per configuration.
        emit: Whether to print the rendered summary.

    Returns:
        The run's outcome: the completed configurations (baseline first,
        iterable directly) and any a defect contained, each with its
        diagnosis.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation; in
            particular a service that resolves to a code-registered binding.
            A load-time refusal stops the whole run up front; only a runtime
            defect during a configuration's sampling is contained per
            configuration.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    registry = bindings._registry if bindings is not None else discover_registrations(contract_path)
    services = discover_services(contract_path, registry)
    configurations, sizing, notes = instantiate_explore(
        declaration, services, registry, samples_per_config=samples_per_config
    )
    if emit:
        print(render_run_plan(sizing.samples, sizing.provenance, per_configuration=True))
        for note in notes:
            print(f"note: {note}")

    explored: list[ConfigurationExploration] = []
    aborted: list[AbortedConfiguration] = []
    for configuration in configurations:
        stem_source = tuple(configuration.factors.items())
        record_label = exploration_stem(stem_source)
        try:
            result = execute(
                configuration.contract,
                configuration.plan,
                on_sample=_tty_progress(record_label) if emit else None,
                record_samples=True,  # projections are the artefact's triage payload
            )
        except DefectDiagnosisError as defect:
            # Contain the defect to this configuration: its paid spend is
            # lost, but every remaining configuration's is not. Record the
            # diagnosis and carry on — the run reports the partial outcome.
            aborted.append(
                AbortedConfiguration(factors=dict(configuration.factors), diagnosis=str(defect))
            )
            if emit:
                print(f"note: configuration {record_label} aborted — {defect}", file=sys.stderr)
            continue
        record = ExplorationRecord.from_run_result(
            result,
            factors=configuration.factors,
            configuration=configuration.configuration,
        )
        artefact = write_exploration(record, Path(explorations_dir))
        explored.append(
            ConfigurationExploration(
                factors=dict(configuration.factors), result=result, path=artefact
            )
        )

    if emit:
        print(
            render_explorations(
                declaration.contract,
                sizing.samples,
                [(e.path.stem, e.result, e.path.as_posix()) for e in explored],
            )
        )
        for entry in aborted:
            label = exploration_stem(tuple(entry.factors.items()))
            print(f"  configuration {label} aborted with a defect (no artefact written)")
    return ExplorationRun(completed=tuple(explored), aborted=tuple(aborted))
