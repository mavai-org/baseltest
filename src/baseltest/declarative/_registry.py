"""Registries: named bindings, checks, and transforms, resolved at contract-load time.

``@binding`` and ``@binding_factory`` register **service types** — user
entries in the same registry the built-in ``language-model`` type lives in
(see the types module). ``@check`` and ``@transform`` register the named
predicates and transformations criteria reference.
"""

import hashlib
import inspect
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import ContractConfigurationError
from ._signatures import SCALAR_TYPES as _SCALAR_TYPES
from ._signatures import kebab as _kebab
from ._signatures import rendered_signature as _rendered_signature
from ._signatures import snake as _snake
from ._signatures import value_fits as _value_fits
from ._steppers import clear_user_steppers
from ._types import (
    ServiceTypeContract,
    clear_user_types,
    find_type,
    has_user_type,
    register_user_type,
)

_F = TypeVar("_F", bound=Callable[..., Any])

_STOCK_TRANSFORMS = ("json", "xml", "yaml")

# Provenance keys the framework itself writes into every baseline artefact:
# the binding name, the run-identity keys, and the service-type marker. A
# covariate or configuration key under one of these names would collide
# with the framework's own entry, so registration and parsing refuse it.
RESERVED_COVARIATE_KEYS = frozenset({"binding", "runMode", "serviceType", "taskFile", "taskFormat"})

_checks: dict[str, Callable[[Any], bool]] = {}
_transforms: dict[str, "TransformRegistration"] = {}


def _register(
    registry: dict[str, Any], kind: str, name: str, fn: Any, reserved: tuple[str, ...] = ()
) -> None:
    if not name:
        raise ContractConfigurationError(f"a {kind} name must be non-empty")
    if name in reserved:
        raise ContractConfigurationError(
            f"{kind} name {name!r} is reserved for the format's stock {kind}s"
        )
    if name in registry:
        raise ContractConfigurationError(
            f"a {kind} named {name!r} is already registered; names must be unique"
        )
    registry[name] = fn


def _register_type(name: str, kind: str, contract: ServiceTypeContract) -> None:
    if not name:
        raise ContractConfigurationError(f"a {kind} name must be non-empty")
    if has_user_type(name):
        raise ContractConfigurationError(
            f"a binding named {name!r} is already registered; names must be unique"
        )
    register_user_type(contract)


def binding(name: str, *, covariates: dict[str, str] | None = None) -> Callable[[_F], _F]:
    """Register the code that invokes a service, under the name contract files use.

    The decorated callable accepts the contract's per-sample input values
    and returns one response string. An anticipated bad response is
    returned (for the criteria to judge); only genuine defects raise, and
    a raising binding aborts the run. It must be safe to invoke once per
    sample.

    A bare binding takes no configuration; a services-file entry naming
    its type is refused with a pointer to :func:`binding_factory`, the
    configurable registration form.

    Args:
        name: The service name contract files reference (also the type
            name a services-file entry could reference).
        covariates: Computed identity the service runs under — values a
            services file cannot state, resolved from the environment (a
            content fingerprint, a library version). A measure run records
            them in the baseline artefact's provenance; a later test whose
            resolved covariates differ is refused with the drifted key(s)
            named. Compute the values at declaration time so every run
            re-resolves them — that is what makes drift observable.
    """
    declared = _validated_covariates(name, covariates)

    def decorate(fn: _F) -> _F:
        _register_type(name, "binding", _bare_type(name, fn, declared))
        return fn

    return decorate


def binding_factory(name: str, *, covariates: dict[str, str] | None = None) -> Callable[[_F], _F]:
    """Register a configurable service type: a factory that constructs the binding.

    The decorated factory receives one grid point's resolved configuration
    as keyword arguments — services-file kebab-case keys map to the
    factory's snake_case parameters — and returns the per-sample callable.
    The factory's signature *is* the configuration schema: parameters with
    defaults are the optional keys, annotations are checked where present,
    and a services-file entry that does not fit is refused at load time
    with the signature in the message.

    Factories run at contract-load time (validation constructs the
    per-sample callable before any sample), so they must be cheap and
    side-effect-light.

    Args:
        name: The type name services-file entries reference via ``type:``.
        covariates: As on :func:`binding` — computed identity, merged into
            the same provenance the resolved configuration feeds. A key
            declared both as a covariate and as a factory parameter is a
            configuration error.
    """
    declared = _validated_covariates(name, covariates)

    def decorate(factory: _F) -> _F:
        _vet_factory_signature(name, factory)
        _register_type(name, "binding factory", _factory_type(name, factory, declared))
        return factory

    return decorate


def _validated_covariates(name: str, covariates: dict[str, str] | None) -> dict[str, str]:
    """Refuse malformed or framework-colliding covariates at registration time."""
    if covariates is None:
        return {}
    for key, value in covariates.items():
        if not isinstance(key, str) or not key:
            raise ContractConfigurationError(
                f"binding {name!r}: covariate keys must be non-empty strings, got {key!r}"
            )
        if key in RESERVED_COVARIATE_KEYS:
            reserved = ", ".join(sorted(RESERVED_COVARIATE_KEYS))
            raise ContractConfigurationError(
                f"binding {name!r}: covariate key {key!r} is reserved for the framework's "
                f"own provenance entries ({reserved}) — choose another name"
            )
        if not isinstance(value, str):
            raise ContractConfigurationError(
                f"binding {name!r}: covariate {key!r} must be a string, got "
                f"{type(value).__name__} — format the value explicitly; identity is "
                "compared verbatim"
            )
    return dict(covariates)


def _bare_type(
    name: str, fn: Callable[..., str], covariates: dict[str, str]
) -> ServiceTypeContract:
    """A bare binding as a service type: the degenerate zero-configuration case."""

    def parse(service: str, raw: dict[str, Any], where: str) -> Any:
        raise ContractConfigurationError(
            f"service {service!r}: type {name!r} is registered with @binding and takes "
            "no configuration — register it with @binding_factory to declare "
            "configurable parameters"
        )

    return ServiceTypeContract(
        name=name,
        builtin=False,
        addressable=True,
        covariates=covariates,
        parse=parse,
        parameter_order=lambda keys: keys,
        resolved_values=lambda _parameters: {},
        provenance=lambda _parameters: dict(covariates),
        invoker=lambda _parameters: fn,
        accepts_configuration_key=lambda _key: False,
    )


def _vet_factory_signature(name: str, factory: Callable[..., Any]) -> None:
    """Every factory parameter must be reachable from a configuration key."""
    for parameter in inspect.signature(factory).parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            raise ContractConfigurationError(
                f"binding factory {name!r}: parameter {parameter.name!r} is not "
                "keyword-bindable — configuration keys bind by name, so factory "
                "parameters must be ordinary or keyword-only"
            )


def _factory_type(
    name: str, factory: Callable[..., Any], covariates: dict[str, str]
) -> ServiceTypeContract:
    """A configurable user type: the factory's signature is its schema."""
    signature = inspect.signature(factory)
    parameters = signature.parameters
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    named = {p.name for p in parameters.values() if p.kind is not inspect.Parameter.VAR_KEYWORD}
    required = {
        p.name
        for p in parameters.values()
        if p.default is inspect.Parameter.empty and p.kind is not inspect.Parameter.VAR_KEYWORD
    }

    def accepts_key(key: str) -> bool:
        return accepts_any or _snake(key) in named

    def parse(service: str, raw: dict[str, Any], where: str) -> dict[str, Any]:
        rendered = _rendered_signature(name, factory)
        for key, value in raw.items():
            key = str(key)
            if key in RESERVED_COVARIATE_KEYS:
                raise ContractConfigurationError(
                    f"service {service!r}: {where}: `{key}:` collides with a provenance "
                    "entry the framework writes itself — choose another name"
                )
            if key in covariates:
                raise ContractConfigurationError(
                    f"service {service!r}: {where}: `{key}:` is already declared as a "
                    f"covariate on the {name!r} registration — one identity key, one "
                    "feed; drop one of the two declarations"
                )
            if not isinstance(value, _SCALAR_TYPES):
                raise ContractConfigurationError(
                    f"service {service!r}: {where}: `{key}:` must be a scalar "
                    f"(string, number, or boolean), got {type(value).__name__}"
                )
            if not accepts_key(key):
                accepted = ", ".join(_kebab(p) for p in sorted(named)) or "(none)"
                raise ContractConfigurationError(
                    f"service {service!r}: {where} has unknown key `{key}:` — the type "
                    f"{name!r} accepts: {accepted}; its factory's signature is {rendered}"
                )
            annotation = parameters[_snake(key)].annotation if _snake(key) in named else None
            if annotation in _SCALAR_TYPES and not _value_fits(value, annotation):
                raise ContractConfigurationError(
                    f"service {service!r}: {where}: `{key}:` expects "
                    f"{annotation.__name__}, got {type(value).__name__} ({value!r}) — "
                    f"the factory's signature is {rendered}"
                )
        missing = sorted(required - {_snake(str(key)) for key in raw})
        if missing:
            keys = ", ".join(f"`{_kebab(m)}:`" for m in missing)
            raise ContractConfigurationError(
                f"service {service!r}: {where} is missing {keys} — required by the "
                f"type {name!r}, whose factory's signature is {rendered}"
            )
        return {str(key): value for key, value in raw.items()}

    def provenance(resolved: dict[str, Any]) -> dict[str, str]:
        entries = {"serviceType": name}
        for key, value in resolved.items():
            entries[key] = value if isinstance(value, str) else json.dumps(value)
        entries.update(covariates)
        return entries

    def invoker(resolved: dict[str, Any]) -> Callable[..., str]:
        produced = factory(**{_snake(key): value for key, value in resolved.items()})
        if not callable(produced):
            raise ContractConfigurationError(
                f"type {name!r}: the factory returned {type(produced).__name__}, not "
                "the per-sample callable — a binding factory constructs the code that "
                "is invoked once per sample"
            )
        result: Callable[..., str] = produced
        return result

    return ServiceTypeContract(
        name=name,
        builtin=False,
        addressable=False,
        covariates=covariates,
        parse=parse,
        parameter_order=lambda keys: keys,
        resolved_values=lambda resolved: dict(resolved),
        provenance=provenance,
        invoker=invoker,
        accepts_configuration_key=accepts_key,
    )


@dataclass(frozen=True, slots=True)
class TransformRegistration:
    """One registered transformation: the callable and its declared shape.

    Attributes:
        fn: The transformation callable.
        output_schema: The declared JSON Schema of the transformation's
            output, when declared — enables static ``path:`` validation
            at load time and always-on per-trial output validation.
        fingerprint: The canonical sha256 fingerprint of the declared
            schema, recorded descriptively in baseline artefacts (an
            output schema executes after the response exists and has no
            influence on the service's behaviour, so it is never a
            covariate); ``None`` when no schema is declared.
    """

    fn: Callable[[str], Any]
    output_schema: dict[str, Any] | None = None
    fingerprint: str | None = None


def _loaded_schema(name: str, output_schema: Any) -> dict[str, Any]:
    """Resolve the declared schema (mapping, or path to a schema file) and vet it."""
    schema = output_schema
    if isinstance(schema, (str, PurePath)):
        path = Path(schema)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ContractConfigurationError(
                f"transform {name!r}: cannot read output schema file {path}: {error}"
            ) from error
        try:
            if path.suffix.lower() in (".yaml", ".yml"):
                yaml = YAML(typ="safe", pure=True)
                schema = yaml.load(io.StringIO(text))
            else:
                schema = json.loads(text)
        except (ValueError, YAMLError) as error:
            raise ContractConfigurationError(
                f"transform {name!r}: output schema file {path} does not parse: {error}"
            ) from error
    if not isinstance(schema, dict):
        raise ContractConfigurationError(
            f"transform {name!r}: `output_schema` must be a mapping (the JSON Schema "
            f"of the transformation's output) or a path to a schema file, got "
            f"{type(schema).__name__}"
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ContractConfigurationError(
            f"transform {name!r}: the declared output schema is not a valid JSON "
            f"Schema: {error.message}"
        ) from error
    return schema


def check(name: str) -> Callable[[_F], _F]:
    """Register a named predicate for the ``satisfies:`` postcondition form.

    The predicate receives the value under judgement (the transformed value
    when the criterion declares a transform, the raw response text
    otherwise) and returns whether the check holds.
    """

    def decorate(fn: _F) -> _F:
        _register(_checks, "check", name, fn)
        return fn

    return decorate


def transform(
    name: str,
    *,
    output_schema: dict[str, Any] | str | PurePath | None = None,
) -> Callable[[_F], _F]:
    """Register a named transformation for the ``transform:`` key.

    The callable receives the raw response and returns the value under
    judgement. Raise :class:`baseltest.contract.TransformError` when the
    response cannot be transformed — that is a failed trial, not an abort;
    any other exception is treated as a defect.

    Args:
        name: The registry name ``transforms:`` entries reference.
        output_schema: The JSON Schema of the transformation's output — a
            mapping, or a path to a schema file (``.json``, or
            ``.yaml``/``.yml``). Declaring it buys two things: contract
            ``path:`` expressions over the transformation's views are
            statically validated against it at load time (the check
            verb's path ↔ shape join), and every trial's actual output is
            validated against it — a violation is a named trial failure,
            never a silent empty selection. A malformed schema is refused
            at registration. The schema's canonical fingerprint is
            recorded descriptively in baseline artefacts — never as a
            covariate: an output schema executes after the response
            exists and has no influence on the service's stochastic
            behaviour, so it is definitionally outside the drift-checked
            identity (the response-schema, by contrast, always influences
            the service and is always a covariate).
    """
    schema = _loaded_schema(name, output_schema) if output_schema is not None else None
    fingerprint = None
    if schema is not None:
        canonical = json.dumps(schema, sort_keys=True)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def decorate(fn: _F) -> _F:
        registration = TransformRegistration(fn=fn, output_schema=schema, fingerprint=fingerprint)
        _register(_transforms, "transform", name, registration, reserved=_STOCK_TRANSFORMS)
        return fn

    return decorate


def has_binding(name: str) -> bool:
    """Whether a bindings-file registration exists under this name."""
    return has_user_type(name)


def _registered_type(name: str) -> ServiceTypeContract:
    contract = find_type(name)
    if contract is None or contract.builtin:
        raise ContractConfigurationError(
            f"service {name!r} is not a registered binding. Register the code that "
            f"invokes your service with @binding({name!r}) before running the contract."
        )
    return contract


def resolve_binding(name: str) -> Callable[..., str]:
    """Look up a bare binding at contract-load time; unresolvable names are refused."""
    contract = _registered_type(name)
    if not contract.addressable:
        raise ContractConfigurationError(
            f"service {name!r} names the configurable type {name!r} directly — a "
            "configurable type is instantiated by a services-file entry; declare a "
            f"service with `type: {name}` (and its `configuration:`) in mavai-services.yaml"
        )
    return contract.invoker(None)


def binding_covariates(name: str) -> dict[str, str]:
    """A registered binding's declared covariates; unresolvable names are refused.

    These are the binding's computed identity — recorded by a measure run
    into the baseline artefact's provenance and compared, key by key, when
    a later test resolves that baseline.
    """
    return dict(_registered_type(name).covariates)


def resolve_check(name: str) -> Callable[[Any], bool]:
    """Look up a named check at contract-load time; unresolvable names are refused."""
    if name not in _checks:
        raise ContractConfigurationError(
            f"satisfies: {name!r} is not a registered check. Register the predicate "
            f"with @check({name!r}) before running the contract."
        )
    return _checks[name]


def resolve_transform(name: str) -> Callable[[str], Any]:
    """Look up a named transform at contract-load time; unresolvable names are refused."""
    return transform_registration(name).fn


def transform_registration(name: str) -> TransformRegistration:
    """The full registration record; unresolvable names are refused."""
    if name not in _transforms:
        raise ContractConfigurationError(
            f"transform: {name!r} is neither a stock transform (json, xml, yaml) nor a "
            f"registered one. Register the transformation with @transform({name!r}) "
            "before running the contract."
        )
    registration: TransformRegistration = _transforms[name]
    return registration


def clear_registries() -> None:
    """Reset all user registries. Test seam only."""
    clear_user_types()
    clear_user_steppers()
    _checks.clear()
    _transforms.clear()
