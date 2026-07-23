"""Optimize instantiation: one runnable configuration per iteration.

The posture is explore's: every criterion participates descriptively — no
thresholds are consulted, no verdict rendered. The invoker is the strict
one measure and test use: an optimize run's iterations must stay
comparable, so a configuration the service type cannot honour is refused,
not degraded.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace as _replace
from types import MappingProxyType
from typing import Any

from baseltest.contract import ServiceContract
from baseltest.engine import Intent, RunKind, RunPlan

from .._errors import ContractConfigurationError
from .._parser import ContractDeclaration
from .._registry import Registry
from .._services import ServiceDefinition, configuration_values
from ._postconditions import _build_criterion, _expected_postconditions
from ._service import _resolve_service, _splat_tuple_invoke, _validate_inputs, _validate_media
from ._views import _build_views


@dataclass(frozen=True, slots=True)
class OptimizePoint:
    """One optimize iteration's configuration, ready to run.

    ``configuration`` is the full resolved map the iteration runs under —
    what the stepper receives as ``current``, and what the artefact's
    iteration entry records.
    """

    parameters: Any
    configuration: Mapping[str, Any]
    contract: ServiceContract[Any]
    plan: RunPlan

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", MappingProxyType(dict(self.configuration)))


def optimize_definition(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None,
    registry: Registry,
) -> ServiceDefinition:
    """The service definition an optimize run drives — refused when there is none.

    An optimize run, like an explore run, requires a service declared in
    the services file: a bare binding carries no configuration for a
    stepper to move.
    """
    definition = (services or {}).get(declaration.service)
    if definition is None:
        if registry.find_type(declaration.service) is not None:
            raise ContractConfigurationError(
                f"optimize requires a declared service: {declaration.service!r} is a "
                "registered type with no services-file entry, so it carries no "
                "configuration for a stepper to move — declare a service of this "
                "type (and its `optimizations:` entries) in the services file"
            )
        _resolve_service(declaration.service, {}, registry)  # raises the standard refusal
        raise AssertionError("unreachable: unresolvable services are refused above")
    if not definition.optimizations:
        raise ContractConfigurationError(
            f"service {declaration.service!r} declares no `optimizations:` section — "
            "add one entry per optimize run (a stepper, `max-iterations`, and "
            "optionally an `initial:` overlay) in the services file"
        )
    return definition


def instantiate_optimize_point(
    declaration: ContractDeclaration,
    definition: ServiceDefinition,
    parameters: Any,
    samples: int,
    registry: Registry,
) -> OptimizePoint:
    """Instantiate one optimize iteration's runnable configuration.

    The posture is explore's: every criterion participates descriptively —
    no thresholds are consulted, no verdict rendered — at whatever sample
    count the invocation chose. The invoker is the strict one measure and
    test use: an optimize run's iterations must stay comparable, so a
    configuration the service type cannot honour is refused, not degraded.
    """
    per_sample = definition.type.invoker(parameters)
    _validate_inputs(declaration.service, per_sample, declaration.inputs)
    _validate_media(parameters, declaration.inputs)
    transforms = declaration.transforms
    views = _build_views(declaration, registry)
    expected = _expected_postconditions(declaration.expected_pairs, transforms, registry)
    criteria = tuple(
        _replace(
            _build_criterion(entry, declaration.confidence, expected, transforms, registry),
            threshold=None,
        )
        for entry in declaration.criteria
    )
    contract = ServiceContract(
        contract_id=declaration.contract,
        invoke=_splat_tuple_invoke(per_sample),
        criteria=criteria,
        views=views,
    )
    plan = RunPlan(
        samples=samples,
        inputs=declaration.inputs,
        kind=RunKind.OPTIMIZE,
        intent=Intent.SMOKE,
    )
    return OptimizePoint(
        parameters=parameters,
        configuration=configuration_values(definition, parameters),
        contract=contract,
        plan=plan,
    )
