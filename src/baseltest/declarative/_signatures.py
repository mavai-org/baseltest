"""Signature-binding helpers shared by the configurable registration forms.

A services-file mapping binds to a Python callable's signature in two
places — a binding factory's configuration and a stepper factory's
``stepper-config:`` — under one rule: kebab-case keys map to snake_case
parameters, parameters with defaults are the optional keys, and scalar
annotations are checked where declared.
"""

import inspect
from collections.abc import Callable
from typing import Any

SCALAR_TYPES = (str, int, float, bool)


def snake(key: str) -> str:
    """A kebab-case configuration key as its snake_case parameter name."""
    return key.replace("-", "_")


def kebab(parameter_name: str) -> str:
    """A snake_case parameter name as its kebab-case configuration key."""
    return parameter_name.replace("_", "-")


def rendered_signature(name: str, fn: Callable[..., Any]) -> str:
    """The introspected signature, rendered for refusal messages."""
    return f"{name}{inspect.signature(fn)}"


def value_fits(value: Any, annotation: Any) -> bool:
    """Whether a YAML scalar satisfies a scalar annotation (bool is not int)."""
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if annotation is float:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if annotation is str:
        return isinstance(value, str)
    return True
