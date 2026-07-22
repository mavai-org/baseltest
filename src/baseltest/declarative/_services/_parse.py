"""Parsing the services file: definitions, explorations, and optimizations.

``parse_services`` reads the ``mavai-services/1`` file and resolves each
entry's type against the registry; ``_parse_definition`` validates one
entry's configuration, exploration grid, and optimizations;
``discover_services`` loads from the conventional locations.
"""

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .._optimize import OptimizationDeclaration, parse_optimizations
from .._types import ServiceTypeContract
from ._model import (
    SERVICES_FILENAME,
    SERVICES_FORMAT_IDENTIFIER,
    ServiceDefinition,
    _fail,
)

if TYPE_CHECKING:
    from .._registry import Registry

_DEFINITION_KEYS = {"type", "configuration", "explorations", "optimizations"}


def _resolved_point(
    type_contract: ServiceTypeContract, parameters: Any
) -> tuple[tuple[str, str], ...]:
    """A configuration's identity: its resolved covariate values, nothing else.

    Resolution has already happened by the time this is called — deltas
    applied, environment defaults filled in (via the same rule provenance
    uses) — so how a grid point was expressed in the file cannot influence
    its identity.
    """
    return tuple(sorted(type_contract.provenance(parameters).items()))


def _parse_explorations(
    name: str,
    entries: Any,
    baseline: dict[str, Any],
    type_contract: ServiceTypeContract,
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    """Resolve the ``explorations:`` entries over the baseline record.

    Each entry declares only deviations; its resolution is the baseline
    with those keys replaced. Two entries resolving to the same covariate
    point — or an entry restating the baseline — are refused: one
    population, one grid point (and one output filename).
    """
    if not isinstance(entries, list) or not entries:
        raise _fail(
            f"service {name!r}: `explorations:` must be a non-empty list of "
            "entries, each declaring the configuration values it replaces"
        )
    ordered: list[str] = list(baseline)
    swept: set[str] = set()
    resolved: list[Any] = []
    for index, entry in enumerate(entries, start=1):
        where = f"exploration entry {index}"
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r}: {where} must be a mapping of replacement values")
        for key, value in entry.items():
            if value is None:
                raise _fail(
                    f"service {name!r}: {where}: `{key}:` declares no value — an "
                    "entry states replacements; omit a key to keep its baseline value"
                )
            if key not in ordered:
                ordered.append(key)
        merged = {**baseline, **entry}
        resolved.append(type_contract.parse(name, merged, where))
        swept.update(entry)
    seen: dict[tuple[tuple[str, str], ...], str] = {
        _resolved_point(type_contract, type_contract.parse(name, baseline, "configuration")): (
            "the baseline `configuration:`"
        )
    }
    for index, parameters in enumerate(resolved, start=1):
        point = _resolved_point(type_contract, parameters)
        previous = seen.get(point)
        if previous is not None:
            raise _fail(
                f"service {name!r}: exploration entry {index} resolves to the same "
                f"configuration as {previous} — two grid entries for one population; "
                "each entry must resolve to a distinct covariate point"
            )
        seen[point] = f"exploration entry {index}"
    swept_keys = type_contract.parameter_order(tuple(key for key in ordered if key in swept))
    return tuple(resolved), swept_keys


def _parse_definition(
    name: str, data: dict[str, Any], type_contract: ServiceTypeContract, registry: "Registry"
) -> ServiceDefinition:
    for key in data:
        if key not in _DEFINITION_KEYS:
            if type_contract.accepts_configuration_key(str(key)):
                raise _fail(
                    f"service {name!r}: `{key}:` belongs inside the `configuration:` "
                    "block — every covariate value lives there, uniformly"
                )
            raise _fail(f"service {name!r}: unknown key `{key}:`")
    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        raise _fail(
            f"service {name!r}: a `configuration:` block is required — the complete "
            "set of parameter values the service runs under"
        )
    parameters = type_contract.parse(name, configuration, "configuration")
    explorations: tuple[Any, ...] = ()
    swept_keys: tuple[str, ...] = ()
    if "explorations" in data:
        explorations, swept_keys = _parse_explorations(
            name, data["explorations"], configuration, type_contract
        )
    optimizations: tuple[OptimizationDeclaration, ...] = ()
    if "optimizations" in data:
        optimizations = parse_optimizations(
            name, data["optimizations"], configuration, type_contract, registry
        )
    return ServiceDefinition(
        name=name,
        type=type_contract,
        configuration=parameters,
        explorations=explorations,
        swept_keys=swept_keys,
        optimizations=optimizations,
    )


# mavai-ref: JVI-GGCWP5H — do not remove (resolves in mavai-orchestrator)
def parse_services(text: str, registry: "Registry") -> dict[str, ServiceDefinition]:
    """Parse a service-definition file's text, resolving types against the registry."""
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        data = yaml.load(io.StringIO(text))
    except YAMLError as error:
        raise _fail(f"the services file is not well-formed YAML: {error}") from error
    if not isinstance(data, dict):
        raise _fail("the services file must be a mapping")
    if data.get("format") != SERVICES_FORMAT_IDENTIFIER:
        raise _fail(f"`format:` must be {SERVICES_FORMAT_IDENTIFIER!r}")
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise _fail("`services:` must be a non-empty mapping")
    definitions: dict[str, ServiceDefinition] = {}
    for name, entry in services.items():
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r} must be a mapping")
        service_type = entry.get("type")
        type_contract = registry.find_type(str(service_type)) if service_type is not None else None
        if type_contract is None:
            registered = ", ".join(registry.registered_type_names())
            raise _fail(
                f"service {name!r}: unknown `type: {service_type}` — registered types: "
                f"{registered}{registry.closest_type_hint(str(service_type))} (built-in types "
                "ship with the framework; user types are registered in "
                "mavai-bindings.py with @registry.binding_factory)"
            )
        definitions[str(name)] = _parse_definition(str(name), entry, type_contract, registry)
    return definitions


def discover_services(
    contract_path: Path, registry: "Registry"
) -> dict[str, ServiceDefinition]:
    """Load definitions from the conventional locations, nearest first."""
    for directory in (contract_path.parent, Path.cwd()):
        candidate = directory / SERVICES_FILENAME
        if candidate.is_file():
            return parse_services(candidate.read_text(encoding="utf-8"), registry)
    return {}
