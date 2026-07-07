"""Declarative service definitions: the mavai-services/1 companion file.

A service file defines named services — including the code-free
``language-model`` type — that contract files reference by name. A definition
carries exactly one complete ``configuration:`` block: every covariate
value the service runs under, in one place, communicated to the service
uniformly. (A ``variations:`` grid over the default configuration is the
reserved explore seam and is rejected in v0.) Definitions join code
registrations as a second population source of the binding registry; a
name collision between the two is a configuration defect.
"""

import hashlib
import io
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import ContractConfigurationError
from ._providers import (
    ANTHROPIC_REQUIRED_MAX_TOKENS,
    ENV_MODEL,
    build_invoker,
    resolve_provider,
)

SERVICES_FORMAT_IDENTIFIER = "mavai-services/1"
SERVICES_FILENAME = "mavai-services.yaml"

_DEFINITION_KEYS = {"type", "configuration", "variations"}
_CONFIGURATION_KEYS = {"system-prompt", "provider", "model", "temperature", "response-schema"}


@dataclass(frozen=True, slots=True)
class LanguageModelParameters:
    """One language-model service configuration: its complete covariate values."""

    system_prompt: str
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    response_schema: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """One service entry: its type's single, complete configuration."""

    name: str
    configuration: LanguageModelParameters


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


def _parse_language_model(name: str, data: dict[str, Any]) -> ServiceDefinition:
    for key in data:
        if key not in _DEFINITION_KEYS:
            if key in _CONFIGURATION_KEYS:
                raise _fail(
                    f"service {name!r}: `{key}:` belongs inside the `configuration:` "
                    "block — every covariate value lives there, uniformly"
                )
            raise _fail(f"service {name!r}: unknown key `{key}:`")
    if "variations" in data:
        raise _fail(
            f"service {name!r}: `variations:` is reserved by the mavai service format "
            "for exploration experiments in a future version — see the format's "
            "extension seams documentation"
        )
    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        raise _fail(
            f"service {name!r}: a `configuration:` block is required — the complete "
            "set of parameter values the service runs under"
        )
    for key in configuration:
        if key not in _CONFIGURATION_KEYS:
            raise _fail(f"service {name!r}: configuration has unknown key `{key}:`")
    system_prompt = configuration.get("system-prompt")
    if not isinstance(system_prompt, str) or not system_prompt:
        raise _fail(
            f"service {name!r}: `system-prompt:` is required in the configuration — "
            "a language-model service is a model given a job; without a system "
            "prompt there is a model, but no service to test"
        )
    provider_name = configuration.get("provider")
    if provider_name is not None:
        resolve_provider(str(provider_name))  # unknown names refused at load
    response_schema = configuration.get("response-schema")
    if response_schema is not None and not isinstance(response_schema, dict):
        raise _fail(
            f"service {name!r}: `response-schema:` must be a mapping (the JSON "
            "Schema the model is instructed to satisfy)"
        )
    return ServiceDefinition(
        name=name,
        configuration=LanguageModelParameters(
            system_prompt=system_prompt,
            provider=provider_name,
            model=configuration.get("model"),
            temperature=configuration.get("temperature"),
            response_schema=response_schema,
        ),
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
        if service_type != "language-model":
            raise _fail(
                f"service {name!r}: unknown `type: {service_type}` — supported: language-model"
            )
        definitions[str(name)] = _parse_language_model(str(name), entry)
    return definitions


def discover_services(contract_path: Path) -> dict[str, ServiceDefinition]:
    """Load definitions from the conventional locations, nearest first."""
    for directory in (contract_path.parent, Path.cwd()):
        candidate = directory / SERVICES_FILENAME
        if candidate.is_file():
            return parse_services(candidate.read_text(encoding="utf-8"))
    return {}


def resolved_provenance(parameters: LanguageModelParameters) -> dict[str, str]:
    """The provenance entries a definition-resolved run must carry."""
    entries = {
        "serviceType": "language-model",
        "provider": parameters.provider or "openai-compatible",
        "systemPrompt": parameters.system_prompt,
        "model": parameters.model or os.environ.get(ENV_MODEL, ""),
    }
    if parameters.temperature is not None:
        entries["temperature"] = str(parameters.temperature)
    if parameters.response_schema is not None:
        canonical = json.dumps(parameters.response_schema, sort_keys=True)
        entries["responseSchemaFingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if parameters.provider == "anthropic":
        entries["providerRequiredMaxTokens"] = str(ANTHROPIC_REQUIRED_MAX_TOKENS)
    return entries


def language_model_invoker(parameters: LanguageModelParameters) -> Callable[[str], str]:
    """Build the invocation callable for a language-model service.

    Delegates to the named provider adapter (or the generic
    OpenAI-compatible one): one plain request per invocation, never a
    retry. A transport failure or error response is a defect (the service
    was unreachable, not stochastic); an anticipated bad *answer* is simply
    the response, judged by the criteria.
    """
    return build_invoker(resolve_provider(parameters.provider), parameters)
