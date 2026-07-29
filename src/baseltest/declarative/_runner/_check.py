"""The ``check`` verb: validate every load-time join with zero samples.

The authoring loop's compile step — loads the contract, discovers the
services file and bindings, and runs every load-time join (constructing the
per-sample callable exactly as a run would) without invoking anything.
"""

from pathlib import Path

from baseltest.engine import RunKind
from baseltest.exploration import experiment_directory, exploration_stem

from .._instantiate import instantiate
from .._instantiate._service import _validate_inputs
from .._parser import load_contract
from .._registrations import discover_registrations
from .._registry import Bindings
from .._schema_walk import validate_declared_paths
from .._services import ServiceDefinition, discover_services, factor_values
from ._shared import DEFAULT_EXPLORATIONS_DIR


def check(
    path: str | Path,
    bindings: Bindings | None = None,
    *,
    explorations_dir: str | Path = DEFAULT_EXPLORATIONS_DIR,
) -> tuple[str, ...]:
    """Validate a contract against its services and bindings — zero samples.

    The authoring loop's compile step: loads the contract, discovers the
    services file and the bindings, and runs every load-time join — the
    configuration ↔ factory-signature joins (at services load), the
    service reference's resolution, and the inputs ↔ per-sample-callable
    join — constructing the per-sample callable exactly as a run would,
    for the baseline and for every exploration grid point, without
    invoking anything. A missing baseline is not checked: absence is a
    run-time fact, not a configuration defect.

    Returns one line per validated fact. Raises on the first join that
    fails, with the same refusal a run would give.

    Raises:
        ContractConfigurationError: The first failing join.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    registry = bindings._registry if bindings is not None else discover_registrations(contract_path)
    services = discover_services(contract_path, registry)
    # The baseline path, validated by the machinery a real run uses —
    # check and run cannot drift apart.
    instantiate(declaration, services, registry, mode=RunKind.MEASURE, samples=1)
    facts = [
        f"contract {declaration.contract!r}: {len(declaration.criteria)} criteria, "
        f"{len(declaration.inputs)} inputs"
    ]
    definition = services.get(declaration.service)
    if definition is None:
        facts.append(
            f"service {declaration.service!r}: binding resolved, every input joined "
            "against its signature"
        )
        facts.extend(validate_declared_paths(declaration, None, declaration.service, registry))
        return tuple(facts)
    facts.append(
        f"service {declaration.service!r}: type {definition.type.name!r}, baseline "
        "configuration valid"
    )
    facts.extend(
        validate_declared_paths(
            declaration,
            getattr(definition.configuration, "response_schema", None),
            declaration.service,
            registry,
        )
    )
    for parameters in definition.explorations:
        point, _note = definition.type.prepare_explore_point(parameters)
        _validate_inputs(declaration.service, definition.type.invoker(point), declaration.inputs)
    if definition.explorations:
        count = len(definition.explorations)
        entries = "entry" if count == 1 else "entries"
        facts.append(f"exploration grid: {count} {entries} constructed and joined")
    facts.extend(_stale_artefact_advisory(declaration.contract, definition, explorations_dir))
    for entry in definition.optimizations:
        _validate_inputs(
            declaration.service, definition.type.invoker(entry.parameters), declaration.inputs
        )
    if definition.optimizations:
        count = len(definition.optimizations)
        entries = "entry" if count == 1 else "entries"
        facts.append(
            f"optimizations: {count} {entries} validated — steppers constructed, iteration 0 joined"
        )
        # An inert plateau window is a configuration fact worth stating,
        # though not a refusal: the run simply goes to its cap.
        facts.extend(note for entry in definition.optimizations for note in entry.notes)
    return tuple(facts)


def _stale_artefact_advisory(
    contract: str, definition: ServiceDefinition, explorations_dir: str | Path
) -> list[str]:
    """Name artefacts in the active experiment directory that no current grid point writes.

    The swept-keys layout makes cross-experiment pollution structurally
    impossible; the residual edge is grid *contraction* within unchanged
    swept keys, which still strands points. This pre-flight names what it
    sees — the stale files, and whether the directory's artefacts span
    several run vintages — and deletes nothing: the artefact tree is
    regenerable working output, operator-owned.
    """
    active = Path(explorations_dir) / contract / experiment_directory(definition.swept_keys)
    if not active.is_dir():
        return []
    current_stems = {
        exploration_stem(tuple(factor_values(definition, parameters).items()))
        for parameters in definition.grid
    }
    advisories = []
    vintages = set()
    for artefact in sorted(active.glob("*.yaml")):
        vintage = _generated_date(artefact)
        if vintage is not None:
            vintages.add(vintage)
        if artefact.stem not in current_stems:
            advisories.append(
                f"stale: {artefact.name} — no current grid point resolves to this configuration"
            )
    if len(vintages) > 1:
        spelled = "two" if len(vintages) == 2 else str(len(vintages))
        advisories.append(
            f"note: artefacts span {spelled} run vintages ({', '.join(sorted(vintages))})"
        )
    return advisories


def _generated_date(artefact: Path) -> str | None:
    """The artefact's generation date (the timestamp's date part), or None."""
    try:
        for line in artefact.read_text(encoding="utf-8").splitlines():
            if line.startswith("generatedAt:"):
                return line.split(":", 1)[1].strip().strip('"')[:10]
    except OSError:
        return None
    return None
