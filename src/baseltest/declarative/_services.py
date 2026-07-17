"""Declarative service definitions: the mavai-services/1 companion file.

A service file defines named services that contract files reference by
name. Each entry is a named, configured instance of a **service type** —
a registered implementation: the built-in ``language-model``, or a user
type registered in ``mavai-bindings.py``. A definition carries a complete
``configuration:`` block — the baseline factor record: every covariate
value the service runs under, in one place, communicated to the service
uniformly. An optional ``explorations:`` section extends the baseline
into a configuration grid: each entry declares only the covariates that
deviate from the baseline (entry = baseline with those keys replaced),
and the grid is the baseline plus the entries. A test or measure run
consumes exactly the baseline; an explore run consumes the whole grid.

The grid semantics here are one generic layer; everything type-specific —
configuration validation, canonical key order, provenance projection, the
invoker — is supplied by the type's registry entry. ``language-model`` is
simply the first built-in entry on that seam.
"""

import hashlib
import io
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import ContractConfigurationError
from ._optimize import OptimizationDeclaration, parse_optimizations
from ._providers import (
    ANTHROPIC_REQUIRED_MAX_TOKENS,
    ENV_MODEL,
    build_invoker,
    resolve_provider,
)
from ._types import (
    ServiceTypeContract,
    closest_type_hint,
    find_type,
    register_builtin_type,
    registered_type_names,
)

SERVICES_FORMAT_IDENTIFIER = "mavai-services/1"
SERVICES_FILENAME = "mavai-services.yaml"

_DEFINITION_KEYS = {"type", "configuration", "explorations", "optimizations"}
_CONFIGURATION_KEYS = {
    "system-prompt",
    "provider",
    "model",
    "temperature",
    "top-p",
    "thinking",
    "prompt-caching",
    "response-schema",
}
# Canonical parameter order: stems and factor blocks list swept covariates
# in this order so artefacts from one grid stay field-for-field diffable.
_PARAMETER_ORDER = (
    "system-prompt",
    "provider",
    "model",
    "temperature",
    "top-p",
    "thinking",
    "prompt-caching",
    "response-schema",
)

_THINKING_VALUES = ("adaptive", "none")


@dataclass(frozen=True, slots=True)
class LanguageModelParameters:
    """One language-model service configuration: its complete covariate values."""

    system_prompt: str
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    thinking: str | None = None
    prompt_caching: bool | None = None
    response_schema: dict[str, Any] | None = None


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


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


def _validate_configuration(
    name: str, configuration: dict[str, Any], where: str
) -> LanguageModelParameters:
    """Validate one resolved language-model configuration mapping."""
    for key in configuration:
        if key not in _CONFIGURATION_KEYS:
            raise _fail(f"service {name!r}: {where} has unknown key `{key}:`")
    system_prompt = configuration.get("system-prompt")
    if not isinstance(system_prompt, str) or not system_prompt:
        raise _fail(
            f"service {name!r}: `system-prompt:` is required in the {where} — "
            "a language-model service is a model given a job; without a system "
            "prompt there is a model, but no service to test"
        )
    provider_name = configuration.get("provider")
    if provider_name is not None:
        resolve_provider(str(provider_name))  # unknown names refused at load
    top_p = configuration.get("top-p")
    if top_p is not None and (
        isinstance(top_p, bool) or not isinstance(top_p, int | float) or not 0 < top_p <= 1
    ):
        raise _fail(
            f"service {name!r}: `top-p:` must be a number in (0, 1] — the "
            "cumulative probability mass nucleus sampling draws from"
        )
    thinking = configuration.get("thinking")
    if thinking is not None and thinking not in _THINKING_VALUES:
        values = ", ".join(_THINKING_VALUES)
        raise _fail(f"service {name!r}: `thinking:` must be one of: {values}")
    prompt_caching = configuration.get("prompt-caching")
    if prompt_caching is not None and not isinstance(prompt_caching, bool):
        raise _fail(f"service {name!r}: `prompt-caching:` must be a boolean")
    response_schema = configuration.get("response-schema")
    if response_schema is not None and not isinstance(response_schema, dict):
        raise _fail(
            f"service {name!r}: `response-schema:` must be a mapping (the JSON "
            "Schema the model is instructed to satisfy)"
        )
    return LanguageModelParameters(
        system_prompt=system_prompt,
        provider=provider_name,
        model=configuration.get("model"),
        temperature=configuration.get("temperature"),
        top_p=top_p,
        thinking=thinking,
        prompt_caching=prompt_caching,
        response_schema=response_schema,
    )


def _resolved_point(
    type_contract: ServiceTypeContract, parameters: Any
) -> tuple[tuple[str, str], ...]:
    """A configuration's identity: its resolved covariate values, nothing else.

    Resolution has already happened by the time this is called — deltas
    applied, environment defaults filled in (via the same rule provenance
    uses) — so how a grid point was expressed in the file cannot influence
    its identity.
    """
    return tuple(sorted(type_contract.provenance(parameters).items()))


def _parse_explorations(
    name: str,
    entries: Any,
    baseline: dict[str, Any],
    type_contract: ServiceTypeContract,
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    """Resolve the ``explorations:`` entries over the baseline record.

    Each entry declares only deviations; its resolution is the baseline
    with those keys replaced. Two entries resolving to the same covariate
    point — or an entry restating the baseline — are refused: one
    population, one grid point (and one output filename).
    """
    if not isinstance(entries, list) or not entries:
        raise _fail(
            f"service {name!r}: `explorations:` must be a non-empty list of "
            "entries, each declaring the configuration values it replaces"
        )
    ordered: list[str] = list(baseline)
    swept: set[str] = set()
    resolved: list[Any] = []
    for index, entry in enumerate(entries, start=1):
        where = f"exploration entry {index}"
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r}: {where} must be a mapping of replacement values")
        for key, value in entry.items():
            if value is None:
                raise _fail(
                    f"service {name!r}: {where}: `{key}:` declares no value — an "
                    "entry states replacements; omit a key to keep its baseline value"
                )
            if key not in ordered:
                ordered.append(key)
        merged = {**baseline, **entry}
        resolved.append(type_contract.parse(name, merged, where))
        swept.update(entry)
    seen: dict[tuple[tuple[str, str], ...], str] = {
        _resolved_point(type_contract, type_contract.parse(name, baseline, "configuration")): (
            "the baseline `configuration:`"
        )
    }
    for index, parameters in enumerate(resolved, start=1):
        point = _resolved_point(type_contract, parameters)
        previous = seen.get(point)
        if previous is not None:
            raise _fail(
                f"service {name!r}: exploration entry {index} resolves to the same "
                f"configuration as {previous} — two grid entries for one population; "
                "each entry must resolve to a distinct covariate point"
            )
        seen[point] = f"exploration entry {index}"
    swept_keys = type_contract.parameter_order(tuple(key for key in ordered if key in swept))
    return tuple(resolved), swept_keys


def _parse_definition(
    name: str, data: dict[str, Any], type_contract: ServiceTypeContract
) -> ServiceDefinition:
    for key in data:
        if key not in _DEFINITION_KEYS:
            if type_contract.accepts_configuration_key(str(key)):
                raise _fail(
                    f"service {name!r}: `{key}:` belongs inside the `configuration:` "
                    "block — every covariate value lives there, uniformly"
                )
            raise _fail(f"service {name!r}: unknown key `{key}:`")
    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        raise _fail(
            f"service {name!r}: a `configuration:` block is required — the complete "
            "set of parameter values the service runs under"
        )
    parameters = type_contract.parse(name, configuration, "configuration")
    explorations: tuple[Any, ...] = ()
    swept_keys: tuple[str, ...] = ()
    if "explorations" in data:
        explorations, swept_keys = _parse_explorations(
            name, data["explorations"], configuration, type_contract
        )
    optimizations: tuple[OptimizationDeclaration, ...] = ()
    if "optimizations" in data:
        optimizations = parse_optimizations(
            name, data["optimizations"], configuration, type_contract
        )
    return ServiceDefinition(
        name=name,
        type=type_contract,
        configuration=parameters,
        explorations=explorations,
        swept_keys=swept_keys,
        optimizations=optimizations,
    )


# javai-ref: JVI-GGCWP5H — do not remove (resolves in javai-orchestrator)
def parse_services(text: str) -> dict[str, ServiceDefinition]:
    """Parse a service-definition file's text."""
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        data = yaml.load(io.StringIO(text))
    except YAMLError as error:
        raise _fail(f"the services file is not well-formed YAML: {error}") from error
    if not isinstance(data, dict):
        raise _fail("the services file must be a mapping")
    if data.get("format") != SERVICES_FORMAT_IDENTIFIER:
        raise _fail(f"`format:` must be {SERVICES_FORMAT_IDENTIFIER!r}")
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise _fail("`services:` must be a non-empty mapping")
    definitions: dict[str, ServiceDefinition] = {}
    for name, entry in services.items():
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r} must be a mapping")
        service_type = entry.get("type")
        type_contract = find_type(str(service_type)) if service_type is not None else None
        if type_contract is None:
            registered = ", ".join(registered_type_names())
            raise _fail(
                f"service {name!r}: unknown `type: {service_type}` — registered types: "
                f"{registered}{closest_type_hint(str(service_type))} (built-in types "
                "ship with the framework; user types are registered in "
                "mavai-bindings.py with @binding_factory)"
            )
        definitions[str(name)] = _parse_definition(str(name), entry, type_contract)
    return definitions


def discover_services(contract_path: Path) -> dict[str, ServiceDefinition]:
    """Load definitions from the conventional locations, nearest first."""
    for directory in (contract_path.parent, Path.cwd()):
        candidate = directory / SERVICES_FILENAME
        if candidate.is_file():
            return parse_services(candidate.read_text(encoding="utf-8"))
    return {}


def resolved_provenance(parameters: LanguageModelParameters) -> dict[str, str]:
    """The provenance entries a language-model-resolved run must carry."""
    entries = {
        "serviceType": "language-model",
        "provider": parameters.provider or "openai-compatible",
        "systemPrompt": parameters.system_prompt,
        "model": parameters.model or os.environ.get(ENV_MODEL, ""),
    }
    if parameters.temperature is not None:
        entries["temperature"] = str(parameters.temperature)
    if parameters.top_p is not None:
        entries["topP"] = str(parameters.top_p)
    if parameters.thinking is not None:
        entries["thinking"] = parameters.thinking
    if parameters.prompt_caching is not None:
        entries["promptCaching"] = "true" if parameters.prompt_caching else "false"
    if parameters.response_schema is not None:
        canonical = json.dumps(parameters.response_schema, sort_keys=True)
        entries["responseSchemaFingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if parameters.provider == "anthropic":
        entries["providerRequiredMaxTokens"] = str(ANTHROPIC_REQUIRED_MAX_TOKENS)
    return entries


def _resolved_values(parameters: LanguageModelParameters) -> dict[str, Any]:
    return {
        "system-prompt": parameters.system_prompt,
        "provider": parameters.provider,
        "model": parameters.model or os.environ.get(ENV_MODEL) or None,
        "temperature": parameters.temperature,
        "top-p": parameters.top_p,
        "thinking": parameters.thinking,
        "prompt-caching": parameters.prompt_caching,
        "response-schema": parameters.response_schema,
    }


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


def language_model_invoker(parameters: LanguageModelParameters) -> Callable[[str], str]:
    """Build the invocation callable for a language-model service.

    Delegates to the named provider adapter (or the generic
    OpenAI-compatible one): one plain request per invocation, never a
    retry. A transport failure or error response is a defect (the service
    was unreachable, not stochastic); an anticipated bad *answer* is simply
    the response, judged by the criteria.
    """
    return build_invoker(resolve_provider(parameters.provider), parameters)


def _language_model_explore_point(
    parameters: LanguageModelParameters,
) -> tuple[LanguageModelParameters, str | None]:
    """Announced degradation, never silent: a grid may span providers with
    differing structured-output, prompt-caching, or thinking support, and
    the configuration that actually runs — and its artefact — carries only
    what its provider honoured."""
    provider = resolve_provider(parameters.provider)
    notes: list[str] = []
    if parameters.response_schema is not None and not provider.supports_response_schema:
        parameters = _replace(parameters, response_schema=None)
        notes.append(
            f"provider {parameters.provider!r} has no structured-output "
            "support in this reader — the response-schema is not sent for "
            "this configuration; carry the output shape in the system "
            "prompt if the comparison should stay fair"
        )
    if parameters.prompt_caching and not provider.supports_prompt_caching:
        parameters = _replace(parameters, prompt_caching=None)
        notes.append(
            f"provider {parameters.provider!r} has no prompt-caching support "
            "in this reader — `prompt-caching:` is not sent for this "
            "configuration; its latency is measured uncached"
        )
    if parameters.thinking == "adaptive" and not provider.supports_thinking:
        parameters = _replace(parameters, thinking=None)
        notes.append(
            f"provider {parameters.provider!r} has no thinking support in "
            "this reader — `thinking:` is not sent for this configuration; "
            "its responses are sampled without deliberation"
        )
    return parameters, "; ".join(notes) if notes else None


def _language_model_type() -> ServiceTypeContract:
    """The built-in language-model entry: the first type on the generic seam."""
    return ServiceTypeContract(
        name="language-model",
        builtin=True,
        addressable=False,
        covariates={},
        parse=_validate_configuration,
        parameter_order=lambda keys: tuple(k for k in _PARAMETER_ORDER if k in keys),
        resolved_values=_resolved_values,
        provenance=resolved_provenance,
        invoker=language_model_invoker,
        accepts_configuration_key=lambda key: key in _CONFIGURATION_KEYS,
        prepare_explore_point=_language_model_explore_point,
    )


register_builtin_type(_language_model_type())
