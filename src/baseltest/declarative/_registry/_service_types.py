"""Service types from user registrations: bare bindings and configurable factories.

`_bare_type` wraps a ``@binding`` callable as the degenerate zero-configuration
type; `_factory_type` turns a ``@binding_factory``'s signature into the
configuration schema; `_vet_factory_signature` refuses non-keyword-bindable
factory parameters; `_builtin_service_types` seeds every registry with the
framework-shipped types.
"""

import inspect
import json
from collections.abc import Callable
from typing import Any

from .._errors import ContractConfigurationError
from .._signatures import SCALAR_TYPES as _SCALAR_TYPES
from .._signatures import kebab as _kebab
from .._signatures import rendered_signature as _rendered_signature
from .._signatures import snake as _snake
from .._signatures import value_fits as _value_fits
from .._types import ServiceTypeContract
from ._guards import RESERVED_COVARIATE_KEYS


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


def _builtin_service_types() -> tuple[ServiceTypeContract, ...]:
    """The framework-shipped service types every registry starts with."""
    # Lazy import: the language-model type lives in the services module, which
    # sits above this one; importing it at call time keeps the module graph
    # acyclic while still seeding every fresh registry.
    from .._services import _language_model_type

    return (_language_model_type(),)
