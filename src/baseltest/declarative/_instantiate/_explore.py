"""Explore instantiation: one runnable configuration per grid point.

An explore run is a measure run per configuration with a descriptive
posture: every criterion participates, but thresholds are not consulted,
so the engine characterises without judging, at any sample size.
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
from .._services import ServiceDefinition, configuration_values, factor_values
from ._postconditions import _build_criterion, _expected_postconditions
from ._service import _resolve_service, _splat_tuple_invoke, _validate_inputs
from ._sizing_policy import DEFAULT_SAMPLES, RunSizing
from ._views import _build_views


@dataclass(frozen=True, slots=True)
class ExploreConfiguration:
    """One grid point, ready to run: its factors, contract instance, and plan.

    ``factors`` is the discriminating subset (grid keys that vary — names
    files and labels); ``configuration`` is the full resolved map the
    point runs under, recorded in its artefact.
    """

    parameters: Any
    factors: dict[str, Any]
    configuration: Mapping[str, Any]
    contract: ServiceContract[Any]
    plan: RunPlan

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", MappingProxyType(dict(self.configuration)))


def instantiate_explore(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None,
    registry: Registry,
    samples_per_config: int | None = None,
) -> tuple[tuple[ExploreConfiguration, ...], RunSizing, tuple[str, ...]]:
    """Instantiate one runnable configuration per grid point for an explore run.

    An explore run is a measure run per configuration with a descriptive
    posture: every criterion participates, but thresholds are not
    consulted — the instantiated criteria carry no bar, so the engine
    characterises without judging, at any sample size. The per-configuration
    count is the invocation's (``--samples-per-config``), defaulting to a
    deliberately small figure — triage is small by design.

    A grid may span providers with differing structured-output support.
    Where measure and test refuse a schema an unsupporting provider cannot
    honour (population identity is load-bearing there), an exploration
    degrades honestly instead: the schema is not sent for that
    configuration, and the returned notes say so — the developer exploring
    across providers carries the output shape in the system prompt when
    the comparison should stay fair.

    Returns the configurations (baseline first), the run sizing, and the
    ``(note, ...)`` lines the caller should surface before running.

    Raises:
        ContractConfigurationError: The service resolves to a bare binding —
            explore requires a service declared in the services file, whose
            configuration grid is the factor source.
    """
    definition = (services or {}).get(declaration.service)
    if definition is None:
        if registry.find_type(declaration.service) is not None:
            raise ContractConfigurationError(
                f"explore requires a declared service: {declaration.service!r} is a "
                "registered type with no services-file entry, so it carries no "
                "configuration grid to explore — declare a service of this type "
                "(and its `explorations:` entries) in the services file"
            )
        _resolve_service(declaration.service, {}, registry)  # raises the standard refusal
        raise AssertionError("unreachable: unresolvable services are refused above")
    sizing = (
        RunSizing(samples=samples_per_config, provenance="explicit")
        if samples_per_config is not None
        else RunSizing(samples=DEFAULT_SAMPLES, provenance="default")
    )
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
    configurations = []
    notes: list[str] = []
    for parameters in definition.grid:
        # A type's last look at its grid point (e.g. the language model's
        # structured-output degradation): announced, never silent.
        parameters, note = definition.type.prepare_explore_point(parameters)
        if note is not None:
            notes.append(note)
        per_sample = definition.type.invoker(parameters)
        _validate_inputs(declaration.service, per_sample, declaration.inputs)
        contract = ServiceContract(
            contract_id=declaration.contract,
            invoke=_splat_tuple_invoke(per_sample),
            criteria=criteria,
            views=views,
        )
        plan = RunPlan(
            samples=sizing.samples,
            inputs=declaration.inputs,
            kind=RunKind.EXPLORE,
            intent=Intent.SMOKE,
        )
        configurations.append(
            ExploreConfiguration(
                parameters=parameters,
                factors=factor_values(definition, parameters),
                configuration=configuration_values(definition, parameters),
                contract=contract,
                plan=plan,
            )
        )
    return tuple(configurations), sizing, tuple(notes)
