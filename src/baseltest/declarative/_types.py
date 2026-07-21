"""The service-type registry: one namespace of service implementations.

The ``type:`` field of a services-file entry names a **service
implementation**. Built-in types (``language-model``) are registered by
the framework at import time; ``@binding`` and ``@binding_factory`` add
user types from ``mavai-bindings.py`` to the same registry. A
services-file entry is uniformly a named, configured instance of a type —
built-in versus user-registered is registration provenance, not a
semantic category.

Service names (services-file keys) and type names (this registry) are
separate namespaces: a contract's ``service:`` reference resolves against
service definitions first, and an unconfigured *addressable* type — a
bare ``@binding`` — is directly usable as a service of the same name, the
degenerate zero-configuration instance.
"""

import difflib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ._errors import ContractConfigurationError


def _identity_explore_point(parameters: Any) -> tuple[Any, str | None]:
    return parameters, None


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceTypeContract:
    """What one service type contributes to the generic configuration layer.

    The grid semantics — overlay resolution over the baseline,
    duplicate-point refusal, swept-key derivation, factor/configuration
    projection — are implemented once, in the services module; a type
    supplies only its type-specific residue through these members.

    Attributes:
        name: The registry name the services file's ``type:`` references.
        builtin: Whether the framework (rather than a bindings file)
            registered it.
        addressable: Whether a contract's ``service:`` reference may name
            the type directly, with no services-file entry — the
            degenerate zero-configuration instance (a bare ``@binding``).
        covariates: The type's declared computed identity, merged into
            every provenance projection.
        parse: ``(service_name, raw_configuration, where) -> parameters``.
            Validates one resolved configuration mapping into the type's
            parameters value; raises a configuration error naming the
            offence.
        parameter_order: Canonical ordering of the given configuration
            keys — what makes grid artefacts field-for-field diffable.
        resolved_values: The full resolved configuration of a parameters
            value, for factor projection.
        provenance: The drift-checked identity entries a run under these
            parameters must carry.
        invoker: ``parameters -> per-sample callable``. Runs at contract
            load time, so it must be cheap and side-effect-light.
        accepts_configuration_key: Whether a key belongs inside this
            type's ``configuration:`` block — drives the misplaced-key
            hint.
        prepare_explore_point: Last look at one grid point before an
            explore run: ``parameters -> (parameters, note)``, where a
            non-``None`` note is announced to the operator (e.g. the
            language model's structured-output degradation).
    """

    name: str
    builtin: bool
    addressable: bool
    covariates: Mapping[str, str]
    parse: Callable[[str, dict[str, Any], str], Any]
    parameter_order: Callable[[tuple[str, ...]], tuple[str, ...]]
    resolved_values: Callable[[Any], dict[str, Any]]
    provenance: Callable[[Any], dict[str, str]]
    invoker: Callable[[Any], Callable[..., str]]
    accepts_configuration_key: Callable[[str], bool]
    prepare_explore_point: Callable[[Any], tuple[Any, str | None]] = field(
        default=_identity_explore_point
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "covariates", MappingProxyType(dict(self.covariates)))


_builtin_types: dict[str, ServiceTypeContract] = {}
_user_types: dict[str, ServiceTypeContract] = {}


def register_builtin_type(contract: ServiceTypeContract) -> None:
    """Register a framework-shipped type. Idempotent by name."""
    _builtin_types[contract.name] = contract


def register_user_type(contract: ServiceTypeContract) -> None:
    """Register a bindings-file type; built-in names cannot be shadowed."""
    if contract.name in _builtin_types:
        raise ContractConfigurationError(
            f"{contract.name!r} is a built-in service type and cannot be re-registered "
            "— choose another name"
        )
    _user_types[contract.name] = contract


def find_type(name: str) -> ServiceTypeContract | None:
    """The registered type of this name, or ``None``."""
    return _user_types.get(name) or _builtin_types.get(name)


def has_user_type(name: str) -> bool:
    """Whether a bindings-file registration exists under this name."""
    return name in _user_types


def registered_type_names() -> tuple[str, ...]:
    """Every registered type name, built-ins first, then user types sorted."""
    return (*sorted(_builtin_types), *sorted(_user_types))


def closest_type_hint(name: str) -> str:
    """A ``did you mean`` fragment for an unknown type name, or ``''``."""
    matches = difflib.get_close_matches(name, registered_type_names(), n=1)
    return f" — did you mean {matches[0]!r}?" if matches else ""


def clear_user_types() -> None:
    """Reset the user half of the registry. Test seam only."""
    _user_types.clear()
