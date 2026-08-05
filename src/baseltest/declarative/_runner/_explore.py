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
from baseltest.exploration import experiment_directory, exploration_stem, write_exploration
from baseltest.observation import RunObservation
from baseltest.reporting import render_explorations, render_run_plan

from .._instantiate import instantiate_explore
from .._parser import load_contract
from .._registrations import discover_registrations
from .._registry import Bindings
from .._services import discover_services
from ._shared import DEFAULT_EXPLORATIONS_DIR, _tty_progress

#: What the grid's own ``configuration:`` block is called in run output.
#: A reader locates it by its role in the sweep, not by whatever its
#: factor values happened to spell — and every other configuration is
#: described against it. The family's reports call it the same thing.
BASE_LABEL = "base"


def _display_label(base: bool, name: str | None, identity: str) -> str:
    """What a configuration is called in this run's output.

    The base by its role, then the author's handle where they gave one,
    then the identity its factor values spell.
    """
    if base:
        return BASE_LABEL
    return name or identity


@dataclass(frozen=True, slots=True)
class ConfigurationExploration:
    """One explored configuration: its factors, its run result, its artefact.

    ``configuration_name`` is the author's handle where they gave one — what
    the run reports call this configuration, in place of the identity its
    factor values spell. ``base`` marks the grid's own ``configuration:``
    block, which a reader locates by its role rather than its values.
    """

    factors: dict[str, object]
    result: RunResult
    path: Path
    configuration_name: str | None = None
    base: bool = False


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
    configuration_name: str | None = None
    base: bool = False


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
    # The experiment-level directory names the question the experiment
    # asks — its swept keys — so changing what is swept opens a fresh
    # directory and a superseded artefact can never sit beside fresh
    # ones (instantiation guarantees the definition exists here).
    experiment = experiment_directory(services[declaration.service].swept_keys)
    if emit:
        print(render_run_plan(sizing.samples, sizing.provenance, per_configuration=True))
        for note in notes:
            print(f"note: {note}")

    explored: list[ConfigurationExploration] = []
    aborted: list[AbortedConfiguration] = []
    for configuration in configurations:
        stem_source = tuple(configuration.factors.items())
        # What this configuration is called while it runs, so a reader
        # watching the run reads what the report will call it afterwards.
        record_label = _display_label(
            configuration.base,
            configuration.configuration_name,
            exploration_stem(stem_source),
        )
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
                AbortedConfiguration(
                    factors=dict(configuration.factors),
                    diagnosis=str(defect),
                    configuration_name=configuration.configuration_name,
                    base=configuration.base,
                )
            )
            if emit:
                print(f"note: configuration {record_label} aborted — {defect}", file=sys.stderr)
            continue
        record = RunObservation.from_run_result(
            result,
            factors=configuration.factors,
            configuration=configuration.configuration,
            base_configuration=configuration.base,
            configuration_name=configuration.configuration_name,
        )
        artefact = write_exploration(record, Path(explorations_dir), experiment)
        explored.append(
            ConfigurationExploration(
                factors=dict(configuration.factors),
                result=result,
                path=artefact,
                configuration_name=configuration.configuration_name,
                base=configuration.base,
            )
        )

    if emit:
        print(
            render_explorations(
                declaration.contract,
                sizing.samples,
                [
                    (
                        _display_label(e.base, e.configuration_name, e.path.stem),
                        e.result,
                        e.path.as_posix(),
                    )
                    for e in explored
                ],
            )
        )
        for entry in aborted:
            label = _display_label(
                entry.base,
                entry.configuration_name,
                exploration_stem(tuple(entry.factors.items())),
            )
            print(f"  configuration {label} aborted with a defect (no artefact written)")
    return ExplorationRun(completed=tuple(explored), aborted=tuple(aborted))
