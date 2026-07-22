"""The stepper/scorer contract: the seam types, the proposal, and config binding.

A stepper proposes the next configuration; a scorer turns one iteration's
aggregate into the number the run drives. The proposal is a typed
`StepProposal` carrying the next configuration and the stepper's optional
provenance — replacing the older monkeypatched provenance attribute — while
a stepper that returns a bare mapping (or ``None``) proposes with none.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .._errors import ContractConfigurationError
from .._signatures import (
    SCALAR_TYPES,
    kebab,
    rendered_signature,
    snake,
    value_fits,
)
from ._context import IterationSummary, OptimizeContext


class Phase(StrEnum):
    """The refining-grid stepper's finite-state machine phase."""

    START = "start"
    GRID = "grid"
    CONFIRM = "confirm"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class StepProposal:
    """A stepper's proposal: the next configuration and its optional provenance.

    ``config`` is the whole next configuration mapping, or ``None`` to stop
    the search — so a stop can still carry provenance. ``provenance`` is the
    stepper's runtime residue for the artefact's ``stepper:`` block (the
    refining-grid's selection, the prompt-engineer's meta identity); it is
    read as the last-seen value when the run ends. A stepper that returns a
    bare configuration mapping (or ``None``) proposes with no provenance.
    """

    config: dict[str, Any] | None
    provenance: Mapping[str, object] | None = None


StepFunction = Callable[
    [dict[str, Any], "OptimizeContext"], "StepProposal | dict[str, Any] | None"
]
ScorerFunction = Callable[["IterationSummary"], float]


@dataclass(frozen=True, slots=True)
class StepperRegistration:
    """One registered stepper: its factory and its validation residue.

    Attributes:
        name: The registry name ``stepper:`` entries reference.
        factory: Constructs the step function from the entry's
            ``stepper-config:`` (snake_case keyword arguments).
        configuration_keys: Factory parameters whose *values* name keys of
            the optimized service's configuration — validated to exist
            there at load time (e.g. ``target-key``, ``key``).
        builtin: Whether the framework registered it.
    """

    name: str
    factory: Callable[..., StepFunction]
    configuration_keys: tuple[str, ...] = ()
    builtin: bool = False


def vet_stepper_factory(name: str, factory: Callable[..., StepFunction]) -> None:
    """Every stepper factory parameter must be keyword-bindable.

    Stepper-config keys bind by name, so a positional-only or var-positional
    parameter can never be reached — refused at registration time.
    """
    for parameter in inspect.signature(factory).parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            raise ContractConfigurationError(
                f"stepper {name!r}: parameter {parameter.name!r} is not "
                "keyword-bindable — stepper-config keys bind by name, so factory "
                "parameters must be ordinary or keyword-only"
            )


def bind_stepper_config(
    service: str,
    where: str,
    registration: StepperRegistration,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one entry's ``stepper-config:`` mapping to its factory's signature.

    The same rule as a binding factory's configuration: kebab-case keys
    map to snake_case parameters, parameters with defaults are the
    optional keys, scalar annotations are checked where declared, and a
    mapping that does not fit is refused with the signature in the
    message. Returns the keyword arguments ready for the factory.
    """
    factory = registration.factory
    rendered = rendered_signature(registration.name, factory)
    parameters = inspect.signature(factory).parameters
    named = {p.name for p in parameters.values() if p.kind is not inspect.Parameter.VAR_KEYWORD}
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    required = {
        p.name
        for p in parameters.values()
        if p.default is inspect.Parameter.empty and p.kind is not inspect.Parameter.VAR_KEYWORD
    }
    for key, value in raw.items():
        key = str(key)
        if not isinstance(value, SCALAR_TYPES):
            raise ContractConfigurationError(
                f"service {service!r}: {where}: `{key}:` must be a scalar "
                f"(string, number, or boolean), got {type(value).__name__}"
            )
        if snake(key) not in named and not accepts_any:
            accepted = ", ".join(kebab(p) for p in sorted(named)) or "(none)"
            raise ContractConfigurationError(
                f"service {service!r}: {where} has unknown key `{key}:` — the stepper "
                f"{registration.name!r} accepts: {accepted}; its factory's signature "
                f"is {rendered}"
            )
        annotation = parameters[snake(key)].annotation if snake(key) in named else None
        if annotation in SCALAR_TYPES and not value_fits(value, annotation):
            raise ContractConfigurationError(
                f"service {service!r}: {where}: `{key}:` expects "
                f"{annotation.__name__}, got {type(value).__name__} ({value!r}) — "
                f"the stepper's factory signature is {rendered}"
            )
    missing = sorted(required - {snake(str(key)) for key in raw})
    if missing:
        keys = ", ".join(f"`{kebab(m)}:`" for m in missing)
        raise ContractConfigurationError(
            f"service {service!r}: {where} is missing {keys} — required by the "
            f"stepper {registration.name!r}, whose factory's signature is {rendered}"
        )
    return {snake(str(key)): value for key, value in raw.items()}
