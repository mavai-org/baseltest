"""The public authoring facade: what a ``mavai-bindings.py`` file registers onto.

A :class:`Bindings` is what a bindings-file author constructs and decorates
their code onto — ``@bindings.transform(...)``, ``@bindings.binding(...)``,
``@bindings.check(...)``, ``@bindings.stepper(...)``, ``@bindings.scorer(...)``.
It exposes **only** the six registration decorators; the framework's resolution
surface (looking a registration up by name at run time) lives on the internal
:class:`Registry` it owns, which the loader threads through a run. Two
``Bindings`` are fully independent — two contracts with different registrations
run in one process without cross-talk.
"""

from collections.abc import Callable
from pathlib import PurePath
from typing import Any, TypeVar

from .._steppers import ScorerFunction, StepFunction
from ._core import Registry

_F = TypeVar("_F", bound=Callable[..., Any])


class Bindings:
    """The registrations a contract run resolves against, as an author declares them.

    Construct one in ``mavai-bindings.py`` (the loader discovers it by the
    module-level name ``bindings``) and decorate your code onto it. Every
    method here registers something; nothing here looks a registration up —
    that is the framework's job, on the internal registry this owns.
    """

    def __init__(self) -> None:
        self._registry = Registry()

    def binding(
        self, name: str, *, covariates: dict[str, str] | None = None
    ) -> Callable[[_F], _F]:
        """Register the code that invokes a service, under the name contract files use.

        The decorated callable accepts the contract's per-sample input values
        and returns one response string. Return an anticipated bad response for
        the criteria to judge; only genuine defects raise (a raising binding
        aborts the run). ``covariates`` is computed identity a services file
        cannot state — recorded in a measure run's provenance and compared on a
        later test.
        """
        return self._registry.binding(name, covariates=covariates)

    def binding_factory(
        self, name: str, *, covariates: dict[str, str] | None = None
    ) -> Callable[[_F], _F]:
        """Register a configurable service type: a factory that constructs the binding.

        The decorated factory receives one grid point's resolved configuration
        as keyword arguments (services-file kebab-case keys map to snake_case
        parameters) and returns the per-sample callable. Its signature *is* the
        configuration schema; it runs at contract-load time, so keep it cheap.
        """
        return self._registry.binding_factory(name, covariates=covariates)

    def check(self, name: str) -> Callable[[_F], _F]:
        """Register a named predicate for the ``satisfies:`` postcondition form.

        The predicate receives the value under judgement (the transformed value
        when the criterion declares a transform, the raw response otherwise) and
        returns whether the check holds.
        """
        return self._registry.check(name)

    def transform(
        self, name: str, *, output_schema: dict[str, Any] | str | PurePath | None = None
    ) -> Callable[[_F], _F]:
        """Register a named transformation for the ``transform:`` key.

        The callable receives the raw response and returns the value under
        judgement. Raise :class:`baseltest.contract.TransformError` when the
        response cannot be transformed — a failed trial, not an abort.
        ``output_schema`` (a mapping or a path to a schema file) statically
        validates contract ``path:`` expressions at load time and validates
        every trial's actual output.
        """
        return self._registry.transform(name, output_schema=output_schema)

    def stepper(
        self, name: str, *, configuration_keys: tuple[str, ...] = ()
    ) -> Callable[[Callable[..., StepFunction]], Callable[..., StepFunction]]:
        """Register a stepper factory under the name ``optimizations:`` entries use.

        The decorated callable is a **factory**: its snake_case parameters are
        the entry's ``stepper-config:`` schema, and it returns the step function
        ``step(current, ctx)`` over the whole configuration mapping. State an
        algorithm keeps across iterations lives in the factory's closure scope.
        ``configuration_keys`` names factory parameters whose values must be
        existing configuration keys (validated at load time).
        """
        return self._registry.stepper(name, configuration_keys=configuration_keys)

    def scorer(self, name: str) -> Callable[[ScorerFunction], ScorerFunction]:
        """Register a scorer under the name the ``scorer:`` key references.

        The callable receives one iteration's aggregate summary and returns the
        number the run drives, in objective units.
        """
        return self._registry.scorer(name)
