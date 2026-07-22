"""The service-definition model, the file-format constants, and grid projection.

`ServiceDefinition` is one resolved service entry — a configured type plus
its exploration grid and optimizations; `factor_values`/`configuration_values`
read a single grid point's discriminating factors and full configuration.
"""

from dataclasses import dataclass
from typing import Any

from .._errors import ContractConfigurationError
from .._optimize import OptimizationDeclaration
from .._types import ServiceTypeContract

SERVICES_FORMAT_IDENTIFIER = "mavai-services/1"
SERVICES_FILENAME = "mavai-services.yaml"


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """One service entry: a configured type, plus any exploration grid.

    Attributes:
        name: The service's name — what a contract's ``service:`` references.
        type: The registered service type the entry configures.
        configuration: The baseline factor record, as the type's parsed
            parameters value — the configuration a test or measure run
            consumes.
        explorations: The resolved exploration entries (each already the
            baseline with the entry's keys replaced), in declaration order.
            Empty unless the definition declares an ``explorations:`` section.
        swept_keys: The configuration keys any exploration entry replaces,
            in the type's canonical order — the grid's discriminating factors.
        optimizations: The resolved ``optimizations:`` entries, in
            declaration order — one Optimize experiment each. Only the
            ``optimize`` verb runs them; ``test`` and ``measure`` never
            read them.
    """

    name: str
    type: ServiceTypeContract
    configuration: Any
    explorations: tuple[Any, ...] = ()
    swept_keys: tuple[str, ...] = ()
    optimizations: tuple[OptimizationDeclaration, ...] = ()

    @property
    def grid(self) -> tuple[Any, ...]:
        """Every configuration an explore run samples: baseline first."""
        return (self.configuration, *self.explorations)


def factor_values(definition: ServiceDefinition, parameters: Any) -> dict[str, Any]:
    """One grid point's discriminating factor values, in canonical order.

    The keys are the definition's swept keys; the values are the point's
    resolved covariates (environment defaults applied, per the same rule
    provenance follows). This is what identifies the configuration in
    exploration artefact *filenames* and variant labels.
    """
    resolved = definition.type.resolved_values(parameters)
    return {key: resolved[key] for key in definition.swept_keys}


def configuration_values(definition: ServiceDefinition, parameters: Any) -> dict[str, Any]:
    """One grid point's full resolved configuration, in canonical order.

    Everything the point ran under — swept or constant across the grid —
    with unset keys omitted. This is what the exploration artefact's
    ``factors:`` block records: a reader of any single artefact sees the
    whole configuration, not only the keys that happened to vary.
    """
    resolved = definition.type.resolved_values(parameters)
    return {key: value for key, value in resolved.items() if value is not None}
