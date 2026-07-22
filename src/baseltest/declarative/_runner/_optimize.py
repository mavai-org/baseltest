"""The ``optimize`` verb: select entries and drive each Optimize experiment.

Selects the ``optimizations:`` entries this invocation runs — never guessed
when there are several — and drives each through its loop, one full-history
artefact per run.
"""

from pathlib import Path

from baseltest.reporting import render_run_plan

from .._errors import ContractConfigurationError
from .._instantiate import optimize_definition
from .._optimize import OptimizationDeclaration
from .._parser import load_contract
from .._registrations import discover_registrations
from .._registry import Registry
from .._services import ServiceDefinition, discover_services
from ._optimize_loop import OptimizationOutcome, _drive_optimization
from ._shared import DEFAULT_OPTIMIZATIONS_DIR

# The catalog's Optimize experiment default: sensible for typical LLM
# tuning scenarios, sized by --samples-per-iteration when deliberate.
DEFAULT_SAMPLES_PER_ITERATION = 20


# mavai-ref: JVI-PS5XC2C — do not remove (resolves in mavai-orchestrator)
def optimize(
    path: str | Path,
    *,
    run_id: str | None = None,
    all_entries: bool = False,
    samples_per_iteration: int | None = None,
    optimizations_dir: str | Path = DEFAULT_OPTIMIZATIONS_DIR,
    emit: bool = True,
    registry: Registry | None = None,
) -> tuple[OptimizationOutcome, ...]:
    """Run the contract's Optimize experiments: iterate, score, persist the history.

    Per selected ``optimizations:`` entry this drives the settled loop:
    iteration 0 is the baseline configuration with the entry's ``initial:``
    overlay applied; each subsequent iteration's configuration is the
    stepper's proposal over the whole current configuration. Every
    iteration is a measure run in miniature with the explore verb's
    descriptive posture — no thresholds consulted, no verdict rendered —
    scored by the entry's scorer, with best-tracking in the entry's
    objective direction. The run stops at the iteration cap, on the
    plateau window, or when the stepper stops; one artefact per run
    records the full history.

    Args:
        path: The contract file.
        run_id: The single entry to run. With several entries declared and
            neither this nor ``all_entries``, the selection is refused —
            never guessed.
        all_entries: Run every declared entry.
        samples_per_iteration: Samples per iteration; omitted, the
            catalog's default applies.
        optimizations_dir: The artefact directory; one subdirectory per
            contract, one file per run id.
        emit: Whether to print the rendered summary.

    Returns:
        One outcome per executed run, in declaration order.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared, the selection is ambiguous, or a stepper
            mid-run returns a configuration the service type refuses.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    if registry is None:
        registry = discover_registrations(contract_path)
    services = discover_services(contract_path, registry)
    definition = optimize_definition(declaration, services, registry)
    entries = _select_entries(definition, run_id, all_entries)
    samples = (
        samples_per_iteration
        if samples_per_iteration is not None
        else DEFAULT_SAMPLES_PER_ITERATION
    )
    if emit:
        provenance = "explicit" if samples_per_iteration is not None else "default"
        print(render_run_plan(samples, provenance, per_iteration=True))

    outcomes: list[OptimizationOutcome] = []
    for entry in entries:
        if emit:
            for note in entry.notes:
                print(f"note: {note}")
        outcomes.append(
            _drive_optimization(
                declaration, definition, entry, samples, Path(optimizations_dir), emit, registry
            )
        )
    return tuple(outcomes)


def _select_entries(
    definition: ServiceDefinition, run_id: str | None, all_entries: bool
) -> tuple[OptimizationDeclaration, ...]:
    """The entries this invocation runs — never guessed when there are several."""
    entries = definition.optimizations
    if run_id is not None:
        for entry in entries:
            if entry.run_id == run_id:
                return (entry,)
        available = ", ".join(entry.run_id for entry in entries)
        raise ContractConfigurationError(
            f"service {definition.name!r} declares no optimization with id {run_id!r} "
            f"— declared: {available}"
        )
    if all_entries or len(entries) == 1:
        return entries
    available = ", ".join(entry.run_id for entry in entries)
    raise ContractConfigurationError(
        f"service {definition.name!r} declares {len(entries)} optimizations — name "
        f"the one to run ({available}), or pass --all to run every entry (each is "
        "an independent, potentially expensive experiment)"
    )
