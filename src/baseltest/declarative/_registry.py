"""The registry: named bindings, checks, and transforms, resolved at load time.

A :class:`Registry` is a caller-held object. Bindings, checks, and transforms
register onto an instance — ``@registry.binding(...)``, ``@registry.check(...)``,
``@registry.transform(...)`` — and a run threads that instance through
resolution. ``@binding`` and ``@binding_factory`` register **service types**
(user entries in the same registry the built-in ``language-model`` type lives
in); ``@check`` and ``@transform`` register the named predicates and
transformations criteria reference. Two registries are fully independent: two
contracts with different registrations run in one process without cross-talk,
and a test constructs a fresh registry rather than resetting a global.
"""

import difflib
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
from ._steppers import (
    ScorerFunction,
    StepFunction,
    StepperRegistration,
    builtin_scorers,
    builtin_stepper_registrations,
    vet_stepper_factory,
)
from ._structured import STOCK_TRANSFORMS
from ._types import ServiceTypeContract

_F = TypeVar("_F", bound=Callable[..., Any])

_STOCK_TRANSFORMS = tuple(STOCK_TRANSFORMS)

# Provenance keys the framework itself writes into every baseline artefact:
# the binding name, the run-identity keys, and the service-type marker. A
# covariate or configuration key under one of these names would collide
# with the framework's own entry, so registration and parsing refuse it.
RESERVED_COVARIATE_KEYS = frozenset({"binding", "runMode", "serviceType", "taskFile", "taskFormat"})


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


def _builtin_service_types() -> tuple[ServiceTypeContract, ...]:
    """The framework-shipped service types every registry starts with."""
    # Lazy import: the language-model type lives in the services module, which
    # sits above this one; importing it at call time keeps the module graph
    # acyclic while still seeding every fresh registry.
    from ._services import _language_model_type

    return (_language_model_type(),)


class Registry:
    """The named registrations one contract run resolves against.

    Bindings, checks, and transforms register onto an instance
    (``@registry.binding(...)``); the run threads that instance through
    resolution. Every registry starts seeded with the framework's built-in
    service types; two registries never share user registrations.
    """

    def __init__(self) -> None:
        self._builtin_types: dict[str, ServiceTypeContract] = {}
        self._user_types: dict[str, ServiceTypeContract] = {}
        self._checks: dict[str, Callable[[Any], bool]] = {}
        self._transforms: dict[str, TransformRegistration] = {}
        self._builtin_steppers: dict[str, StepperRegistration] = {}
        self._user_steppers: dict[str, StepperRegistration] = {}
        self._builtin_scorers: dict[str, ScorerFunction] = {}
        self._user_scorers: dict[str, ScorerFunction] = {}
        for contract in _builtin_service_types():
            self._builtin_types[contract.name] = contract
        for registration in builtin_stepper_registrations():
            self._builtin_steppers[registration.name] = registration
        self._builtin_scorers.update(builtin_scorers())

    # -- registration decorators -------------------------------------------

    def binding(self, name: str, *, covariates: dict[str, str] | None = None) -> Callable[[_F], _F]:
        """Register the code that invokes a service, under the name contract files use.

        The decorated callable accepts the contract's per-sample input values
        and returns one response string. An anticipated bad response is
        returned (for the criteria to judge); only genuine defects raise, and
        a raising binding aborts the run. It must be safe to invoke once per
        sample.

        Args:
            name: The service name contract files reference (also the type
                name a services-file entry could reference).
            covariates: Computed identity the service runs under — values a
                services file cannot state, resolved from the environment. A
                measure run records them in the baseline's provenance; a later
                test whose resolved covariates differ is refused. Compute the
                values at declaration time so every run re-resolves them.
        """
        declared = _validated_covariates(name, covariates)

        def decorate(fn: _F) -> _F:
            self._register_type(name, "binding", _bare_type(name, fn, declared))
            return fn

        return decorate

    def binding_factory(
        self, name: str, *, covariates: dict[str, str] | None = None
    ) -> Callable[[_F], _F]:
        """Register a configurable service type: a factory that constructs the binding.

        The decorated factory receives one grid point's resolved configuration
        as keyword arguments — services-file kebab-case keys map to the
        factory's snake_case parameters — and returns the per-sample callable.
        The factory's signature *is* the configuration schema. Factories run at
        contract-load time, so they must be cheap and side-effect-light.

        Args:
            name: The type name services-file entries reference via ``type:``.
            covariates: As on :meth:`binding` — computed identity merged into
                the same provenance the resolved configuration feeds.
        """
        declared = _validated_covariates(name, covariates)

        def decorate(factory: _F) -> _F:
            _vet_factory_signature(name, factory)
            self._register_type(name, "binding factory", _factory_type(name, factory, declared))
            return factory

        return decorate

    def check(self, name: str) -> Callable[[_F], _F]:
        """Register a named predicate for the ``satisfies:`` postcondition form.

        The predicate receives the value under judgement (the transformed value
        when the criterion declares a transform, the raw response text
        otherwise) and returns whether the check holds.
        """

        def decorate(fn: _F) -> _F:
            _register(self._checks, "check", name, fn)
            return fn

        return decorate

    def transform(
        self,
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
                mapping, or a path to a schema file. Declaring it statically
                validates contract ``path:`` expressions at load time and
                validates every trial's actual output; a violation is a named
                trial failure. Its canonical fingerprint is recorded
                descriptively in baseline artefacts, never as a covariate. A
                malformed schema is refused at registration.
        """
        schema = _loaded_schema(name, output_schema) if output_schema is not None else None
        fingerprint = None
        if schema is not None:
            canonical = json.dumps(schema, sort_keys=True)
            fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        def decorate(fn: _F) -> _F:
            registration = TransformRegistration(
                fn=fn, output_schema=schema, fingerprint=fingerprint
            )
            _register(self._transforms, "transform", name, registration, reserved=_STOCK_TRANSFORMS)
            return fn

        return decorate

    # -- the service-type sub-registry -------------------------------------

    def _register_type(self, name: str, kind: str, contract: ServiceTypeContract) -> None:
        if not name:
            raise ContractConfigurationError(f"a {kind} name must be non-empty")
        if self.has_user_type(name):
            raise ContractConfigurationError(
                f"a binding named {name!r} is already registered; names must be unique"
            )
        self.register_user_type(contract)

    def register_user_type(self, contract: ServiceTypeContract) -> None:
        """Register a bindings-file type; built-in names cannot be shadowed."""
        if contract.name in self._builtin_types:
            raise ContractConfigurationError(
                f"{contract.name!r} is a built-in service type and cannot be re-registered "
                "— choose another name"
            )
        self._user_types[contract.name] = contract

    def find_type(self, name: str) -> ServiceTypeContract | None:
        """The registered type of this name, or ``None``."""
        return self._user_types.get(name) or self._builtin_types.get(name)

    def has_user_type(self, name: str) -> bool:
        """Whether a bindings-file registration exists under this name."""
        return name in self._user_types

    def registered_type_names(self) -> tuple[str, ...]:
        """Every registered type name, built-ins first, then user types sorted."""
        return (*sorted(self._builtin_types), *sorted(self._user_types))

    def closest_type_hint(self, name: str) -> str:
        """A ``did you mean`` fragment for an unknown type name, or ``''``."""
        matches = difflib.get_close_matches(name, self.registered_type_names(), n=1)
        return f" — did you mean {matches[0]!r}?" if matches else ""

    # -- resolvers ---------------------------------------------------------

    def has_binding(self, name: str) -> bool:
        """Whether a bindings-file registration exists under this name."""
        return self.has_user_type(name)

    def _registered_type(self, name: str) -> ServiceTypeContract:
        contract = self.find_type(name)
        if contract is None or contract.builtin:
            raise ContractConfigurationError(
                f"service {name!r} is not a registered binding. Register the code that "
                f"invokes your service with @registry.binding({name!r}) before running "
                "the contract."
            )
        return contract

    def resolve_binding(self, name: str) -> Callable[..., str]:
        """Look up a bare binding at contract-load time; unresolvable names are refused."""
        contract = self._registered_type(name)
        if not contract.addressable:
            raise ContractConfigurationError(
                f"service {name!r} names the configurable type {name!r} directly — a "
                "configurable type is instantiated by a services-file entry; declare a "
                f"service with `type: {name}` (and its `configuration:`) in mavai-services.yaml"
            )
        return contract.invoker(None)

    def binding_covariates(self, name: str) -> dict[str, str]:
        """A registered binding's declared covariates; unresolvable names are refused.

        These are the binding's computed identity — recorded by a measure run
        into the baseline artefact's provenance and compared, key by key, when
        a later test resolves that baseline.
        """
        return dict(self._registered_type(name).covariates)

    def resolve_check(self, name: str) -> Callable[[Any], bool]:
        """Look up a named check at contract-load time; unresolvable names are refused."""
        if name not in self._checks:
            raise ContractConfigurationError(
                f"satisfies: {name!r} is not a registered check. Register the predicate "
                f"with @registry.check({name!r}) before running the contract."
            )
        return self._checks[name]

    def resolve_transform(self, name: str) -> Callable[[str], Any]:
        """Look up a named transform at contract-load time; unresolvable names are refused."""
        return self.transform_registration(name).fn

    def transform_registration(self, name: str) -> TransformRegistration:
        """The full registration record; unresolvable names are refused."""
        if name not in self._transforms:
            raise ContractConfigurationError(
                f"transform: {name!r} is neither a stock transform (json, xml, yaml) nor a "
                f"registered one. Register the transformation with @registry.transform({name!r}) "
                "before running the contract."
            )
        registration: TransformRegistration = self._transforms[name]
        return registration

    # -- steppers and scorers ----------------------------------------------

    def stepper(
        self, name: str, *, configuration_keys: tuple[str, ...] = ()
    ) -> Callable[[Callable[..., StepFunction]], Callable[..., StepFunction]]:
        """Register a stepper factory under the name ``optimizations:`` entries use.

        The decorated callable is a **factory**: its snake_case parameters are
        the entry's ``stepper-config:`` schema (kebab-case keys map by name,
        defaults are the optional keys, scalar annotations are checked), and
        it returns the step function — ``step(current, ctx)`` over the whole
        configuration mapping, ``None`` to stop. State an algorithm needs
        across iterations lives in the factory's closure scope.

        Args:
            name: The registry name.
            configuration_keys: Names of factory parameters whose values must
                be existing keys of the optimized service's configuration —
                refused at load time otherwise.
        """

        def decorate(factory: Callable[..., StepFunction]) -> Callable[..., StepFunction]:
            self._register_stepper(
                StepperRegistration(
                    name=name, factory=factory, configuration_keys=configuration_keys
                )
            )
            return factory

        return decorate

    def scorer(self, name: str) -> Callable[[ScorerFunction], ScorerFunction]:
        """Register a scorer under the name ``scorer:`` entries reference.

        The callable receives one iteration's aggregate summary and returns
        the number the run drives, in objective units.
        """

        def decorate(fn: ScorerFunction) -> ScorerFunction:
            if not name:
                raise ContractConfigurationError("a scorer name must be non-empty")
            if name in self._builtin_scorers:
                raise ContractConfigurationError(
                    f"{name!r} is a built-in scorer and cannot be re-registered "
                    "— choose another name"
                )
            if name in self._user_scorers:
                raise ContractConfigurationError(
                    f"a scorer named {name!r} is already registered; names must be unique"
                )
            self._user_scorers[name] = fn
            return fn

        return decorate

    def _register_stepper(self, registration: StepperRegistration) -> None:
        if not registration.name:
            raise ContractConfigurationError("a stepper name must be non-empty")
        if registration.name in self._builtin_steppers:
            raise ContractConfigurationError(
                f"{registration.name!r} is a built-in stepper and cannot be re-registered "
                "— choose another name"
            )
        if registration.name in self._user_steppers:
            raise ContractConfigurationError(
                f"a stepper named {registration.name!r} is already registered; names must be unique"
            )
        vet_stepper_factory(registration.name, registration.factory)
        self._user_steppers[registration.name] = registration

    def find_stepper(self, name: str) -> StepperRegistration | None:
        """The registered stepper of this name, or ``None``."""
        return self._user_steppers.get(name) or self._builtin_steppers.get(name)

    def find_scorer(self, name: str) -> ScorerFunction | None:
        """The registered scorer of this name, or ``None``."""
        return self._user_scorers.get(name) or self._builtin_scorers.get(name)

    def registered_stepper_names(self) -> tuple[str, ...]:
        """Every registered stepper name, built-ins first, then user names sorted."""
        return (*sorted(self._builtin_steppers), *sorted(self._user_steppers))

    def registered_scorer_names(self) -> tuple[str, ...]:
        """Every registered scorer name, built-ins first, then user names sorted."""
        return (*sorted(self._builtin_scorers), *sorted(self._user_scorers))

    def closest_stepper_hint(self, name: str) -> str:
        """A ``did you mean`` fragment for an unknown stepper name, or ``''``."""
        matches = difflib.get_close_matches(name, self.registered_stepper_names(), n=1)
        return f" — did you mean {matches[0]!r}?" if matches else ""
