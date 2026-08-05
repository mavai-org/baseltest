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
from .._roots import Roots
from .._types import FileValueKind, ServiceTypeContract
from ._model import (
    SERVICES_FILENAME,
    SERVICES_FORMAT_IDENTIFIER,
    ServiceDefinition,
    _fail,
)

if TYPE_CHECKING:
    from .._registry import Registry

_DEFINITION_KEYS = {"type", "configuration", "explorations", "optimizations"}


def _references_a_file(value: dict[str, Any], kind: FileValueKind) -> bool:
    """Whether a mapping-valued entry is a ``{file:}`` reference rather than
    an inline value.

    A text key's inline value is a string, so a mapping there can only be
    the file form — malformed spellings included, which keeps their
    refusal specific. A mapping key's inline value is itself a mapping,
    so only the sole-``file`` spelling is the reference; anything else is
    the value written inline.
    """
    return kind is FileValueKind.TEXT or set(value) == {"file"}


def _parsed_mapping(text: str, resolved: Path, location: str) -> dict[str, Any]:
    """One mapping-valued file, parsed as YAML (JSON being a subset of it)."""
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        document = yaml.load(io.StringIO(text))
    except YAMLError as error:
        raise _fail(f"{location}: file {resolved} is not well-formed YAML: {error}") from error
    if not isinstance(document, dict):
        raise _fail(
            f"{location}: file {resolved} holds {_shape(document)}, but this key takes "
            "a mapping — the referenced file must contain what the key's inline value "
            "would have been"
        )
    return document


def _shape(document: Any) -> str:
    """A readable name for what a file parsed to, for the refusal message."""
    if document is None:
        return "nothing"
    if isinstance(document, bool):
        return "a boolean"
    if isinstance(document, list):
        return "a list"
    if isinstance(document, str):
        return "a string"
    if isinstance(document, int | float):
        return "a number"
    return f"a {type(document).__name__}"


def _resolve_file_values(
    name: str,
    mapping: dict[str, Any],
    type_contract: ServiceTypeContract,
    where: str,
    roots: Roots,
    base_dir: Path | None,
) -> dict[str, Any]:
    """Resolve any ``{file: <path>}`` values the type admits to their content.

    Resolution happens before the type's ``parse`` sees the configuration
    — root references included, the file read once at load and decoded as
    UTF-8 — so identity, provenance, and the steppers all see the value
    exactly as if it had been written inline (resolved-as-used): a text
    key its decoded string, a mapping key its parsed document.
    """
    for key, kind in type_contract.file_value_keys.items():
        value = mapping.get(key)
        if not isinstance(value, dict) or not _references_a_file(value, kind):
            continue
        location = f"service {name!r}: {where}: `{key}:`"
        if set(value) != {"file"} or not isinstance(value.get("file"), str) or not value["file"]:
            raise _fail(
                f"{location} file form is `{{file: <path>}}` with a non-empty path and no other key"
            )
        raw = value["file"]
        rooted = roots.resolve(raw, location)
        if rooted is not None:
            resolved = rooted
        elif base_dir is None:
            raise _fail(
                f"{location}: a `{{file:}}` value needs a services file loaded "
                f"from disk to resolve {raw!r} relative to it"
            )
        else:
            resolved = (base_dir / raw).resolve()
        try:
            data = resolved.read_bytes()
        except OSError as error:
            raise _fail(f"{location}: cannot read file {resolved}: {error}") from error
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _fail(f"{location}: file {resolved} is not valid UTF-8 text: {error}") from error
        content = text if kind is FileValueKind.TEXT else _parsed_mapping(text, resolved, location)
        mapping = {**mapping, key: content}
    return mapping


#: The exploration entry's one reserved, non-covariate key.
_NAME_KEY = "configurationName"

#: A handle is shown to a reader, so it is bounded like any displayed value.
_NAME_MAX = 256


def _configuration_name(service: str, value: Any, where: str) -> str | None:
    """An entry's optional handle, validated.

    The handle is for the reader — it reappears in reports so they know
    which configuration was in play — and plays no part in covariate
    space: not in resolution, not in the point, not in the filename. It
    is therefore removed from the entry before anything else looks at it.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _fail(
            f"service {service!r}: {where}: `{_NAME_KEY}:` is a non-empty string — the "
            "handle a reader sees beside this configuration in reports"
        )
    if len(value) > _NAME_MAX:
        raise _fail(
            f"service {service!r}: {where}: `{_NAME_KEY}:` is {len(value)} characters, "
            f"over the {_NAME_MAX} a displayed handle may carry"
        )
    return value


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
    roots: Roots,
    base_dir: Path | None,
) -> tuple[tuple[Any, ...], tuple[str, ...], tuple[str | None, ...]]:
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
    names: list[str | None] = []
    for index, entry in enumerate(entries, start=1):
        where = f"exploration entry {index}"
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r}: {where} must be a mapping of replacement values")
        entry = dict(entry)
        names.append(_configuration_name(name, entry.pop(_NAME_KEY, None), where))
        if not entry:
            raise _fail(
                f"service {name!r}: {where} declares only `{_NAME_KEY}:` — a handle names "
                "a grid point, it does not make one; state the values this entry replaces"
            )
        for key, value in entry.items():
            if value is None:
                raise _fail(
                    f"service {name!r}: {where}: `{key}:` declares no value — an "
                    "entry states replacements; omit a key to keep its baseline value"
                )
            if key not in ordered:
                ordered.append(key)
        entry = _resolve_file_values(name, dict(entry), type_contract, where, roots, base_dir)
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
    return tuple(resolved), swept_keys, tuple(names)


def _parse_definition(
    name: str,
    data: dict[str, Any],
    type_contract: ServiceTypeContract,
    registry: "Registry",
    roots: Roots,
    base_dir: Path | None,
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
    configuration = _resolve_file_values(
        name, dict(configuration), type_contract, "configuration", roots, base_dir
    )
    parameters = type_contract.parse(name, configuration, "configuration")
    explorations: tuple[Any, ...] = ()
    swept_keys: tuple[str, ...] = ()
    exploration_names: tuple[str | None, ...] = ()
    if "explorations" in data:
        explorations, swept_keys, exploration_names = _parse_explorations(
            name, data["explorations"], configuration, type_contract, roots, base_dir
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
        exploration_names=exploration_names,
        optimizations=optimizations,
        roots=roots.disclosures(),
    )


# mavai-ref: JVI-GGCWP5H — do not remove (resolves in mavai-orchestrator)
def parse_services(
    text: str, registry: "Registry", source_path: Path | None = None
) -> dict[str, ServiceDefinition]:
    """Parse a service-definition file's text, resolving types against the registry.

    ``source_path`` locates the file on disk — the anchor for the
    ``roots:`` block and every ``{file: <path>}`` value. Omitted, the
    file may declare neither.
    """
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
    for key in data:
        if key not in ("format", "roots", "services"):
            raise _fail(
                f"the services file has unknown key `{key}:` — it holds `format:`, "
                "an optional `roots:` block, and the `services:` block, nothing else"
            )
    base_dir = source_path.parent if source_path is not None else None
    roots = Roots.parse(data.get("roots"), base_dir, "the services file")
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
                "mavai-bindings.py with @bindings.binding_factory)"
            )
        definitions[str(name)] = _parse_definition(
            str(name), entry, type_contract, registry, roots, base_dir
        )
    roots.refuse_dead()
    return definitions


def discover_services(contract_path: Path, registry: "Registry") -> dict[str, ServiceDefinition]:
    """Load definitions from the conventional locations, nearest first."""
    for directory in (contract_path.parent, Path.cwd()):
        candidate = directory / SERVICES_FILENAME
        if candidate.is_file():
            return parse_services(candidate.read_text(encoding="utf-8"), registry, candidate)
    return {}
