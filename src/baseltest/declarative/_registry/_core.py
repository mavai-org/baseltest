"""The `Registry` class: the named registrations one contract run resolves against.

Bindings, checks, transforms, steppers, and scorers register onto an instance
(``@registry.binding(...)``); the run threads that instance through resolution.
Every registry starts seeded with the framework's built-in service types,
steppers, and scorers; two registries never share user registrations.
"""

import difflib
import hashlib
import json
from collections.abc import Callable
from pathlib import PurePath
from typing import Any, TypeVar

from .._errors import ContractConfigurationError
from .._steppers import (
    ScorerFunction,
    StepFunction,
    StepperRegistration,
    builtin_scorers,
    builtin_stepper_registrations,
    vet_stepper_factory,
)
from .._types import ServiceTypeContract
from ._guards import _register, _validated_covariates
from ._service_types import (
    _bare_type,
    _builtin_service_types,
    _factory_type,
    _vet_factory_signature,
)
from ._transform import _STOCK_TRANSFORMS, TransformRegistration, _loaded_schema

_F = TypeVar("_F", bound=Callable[..., Any])


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
