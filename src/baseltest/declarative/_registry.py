"""Registries: named bindings, checks, and transforms, resolved at task-load time."""

from collections.abc import Callable
from typing import Any, TypeVar

from ._errors import TaskConfigurationError

_F = TypeVar("_F", bound=Callable[..., Any])

_STOCK_TRANSFORMS = ("json", "xml", "yaml")

_bindings: dict[str, Callable[[str], str]] = {}
_checks: dict[str, Callable[[Any], bool]] = {}
_transforms: dict[str, Callable[[str], Any]] = {}


def _register(
    registry: dict[str, Any], kind: str, name: str, fn: Any, reserved: tuple[str, ...] = ()
) -> None:
    if not name:
        raise TaskConfigurationError(f"a {kind} name must be non-empty")
    if name in reserved:
        raise TaskConfigurationError(
            f"{kind} name {name!r} is reserved for the format's stock {kind}s"
        )
    if name in registry:
        raise TaskConfigurationError(
            f"a {kind} named {name!r} is already registered; names must be unique"
        )
    registry[name] = fn


def binding(name: str) -> Callable[[_F], _F]:
    """Register the code that invokes a service, under the name task files use.

    The decorated callable accepts one input string and returns one response
    string. An anticipated bad response is returned (for the criteria to
    judge); only genuine defects raise, and a raising binding aborts the run.
    It must be safe to invoke once per sample.
    """

    def decorate(fn: _F) -> _F:
        _register(_bindings, "binding", name, fn)
        return fn

    return decorate


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


def resolve_binding(name: str) -> Callable[[str], str]:
    """Look up a binding at task-load time; unresolvable names are refused."""
    if name not in _bindings:
        raise TaskConfigurationError(
            f"service {name!r} is not a registered binding. Register the code that "
            f"invokes your service with @binding({name!r}) before running the task."
        )
    return _bindings[name]


def resolve_check(name: str) -> Callable[[Any], bool]:
    """Look up a named check at task-load time; unresolvable names are refused."""
    if name not in _checks:
        raise TaskConfigurationError(
            f"satisfies: {name!r} is not a registered check. Register the predicate "
            f"with @check({name!r}) before running the task."
        )
    return _checks[name]


def resolve_transform(name: str) -> Callable[[str], Any]:
    """Look up a named transform at task-load time; unresolvable names are refused."""
    if name not in _transforms:
        raise TaskConfigurationError(
            f"transform: {name!r} is neither a stock transform (json, xml, yaml) nor a "
            f"registered one. Register the transformation with @transform({name!r}) "
            "before running the task."
        )
    return _transforms[name]


def clear_registries() -> None:
    """Reset all registries. Test seam only."""
    _bindings.clear()
    _checks.clear()
    _transforms.clear()
