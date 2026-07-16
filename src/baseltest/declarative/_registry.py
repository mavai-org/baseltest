"""Registries: named bindings, checks, and transforms, resolved at contract-load time."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ._errors import ContractConfigurationError

_F = TypeVar("_F", bound=Callable[..., Any])

_STOCK_TRANSFORMS = ("json", "xml", "yaml")

# Provenance keys the framework itself writes into every baseline artefact:
# the binding name, the run-identity keys, and the service-type marker the
# services-file path emits. A binding covariate under one of these names
# would collide with the framework's own entry, so registration refuses it.
RESERVED_COVARIATE_KEYS = frozenset({"binding", "runMode", "serviceType", "taskFile", "taskFormat"})


@dataclass(frozen=True, slots=True)
class _RegisteredBinding:
    """One binding registration: the invocation callable and its identity."""

    invoke: Callable[[str], str]
    covariates: dict[str, str] = field(default_factory=dict)


_bindings: dict[str, _RegisteredBinding] = {}
_checks: dict[str, Callable[[Any], bool]] = {}
_transforms: dict[str, Callable[[str], Any]] = {}


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


def binding(name: str, *, covariates: dict[str, str] | None = None) -> Callable[[_F], _F]:
    """Register the code that invokes a service, under the name contract files use.

    The decorated callable accepts one input string and returns one response
    string. An anticipated bad response is returned (for the criteria to
    judge); only genuine defects raise, and a raising binding aborts the run.
    It must be safe to invoke once per sample.

    Args:
        name: The service name contract files reference.
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
        _register(_bindings, "binding", name, _RegisteredBinding(fn, declared))
        return fn

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


def transform(name: str) -> Callable[[_F], _F]:
    """Register a named transformation for the ``transform:`` key.

    The callable receives the raw response and returns the value under
    judgement. Raise :class:`baseltest.contract.TransformError` when the
    response cannot be transformed — that is a failed trial, not an abort;
    any other exception is treated as a defect.
    """

    def decorate(fn: _F) -> _F:
        _register(_transforms, "transform", name, fn, reserved=_STOCK_TRANSFORMS)
        return fn

    return decorate


def has_binding(name: str) -> bool:
    """Whether a code-registered binding exists under this name."""
    return name in _bindings


def _registered_binding(name: str) -> _RegisteredBinding:
    if name not in _bindings:
        raise ContractConfigurationError(
            f"service {name!r} is not a registered binding. Register the code that "
            f"invokes your service with @binding({name!r}) before running the contract."
        )
    return _bindings[name]


def resolve_binding(name: str) -> Callable[[str], str]:
    """Look up a binding at contract-load time; unresolvable names are refused."""
    return _registered_binding(name).invoke


def binding_covariates(name: str) -> dict[str, str]:
    """A registered binding's declared covariates; unresolvable names are refused.

    These are the binding's computed identity — recorded by a measure run
    into the baseline artefact's provenance and compared, key by key, when
    a later test resolves that baseline.
    """
    return dict(_registered_binding(name).covariates)


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
    if name not in _transforms:
        raise ContractConfigurationError(
            f"transform: {name!r} is neither a stock transform (json, xml, yaml) nor a "
            f"registered one. Register the transformation with @transform({name!r}) "
            "before running the contract."
        )
    return _transforms[name]


def clear_registries() -> None:
    """Reset all registries. Test seam only."""
    _bindings.clear()
    _checks.clear()
    _transforms.clear()
