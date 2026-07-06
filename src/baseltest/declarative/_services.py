"""Declarative service definitions: the mavai-services/1 companion file.

A service file defines named services — including the code-free
``language-model`` type — that task files reference by name. A definition
carries exactly one complete ``configuration:`` block: every covariate
value the service runs under, in one place, communicated to the service
uniformly. (A ``variations:`` grid over the default configuration is the
reserved explore seam and is rejected in v0.) Definitions join code
registrations as a second population source of the binding registry; a
name collision between the two is a configuration defect.
"""

import io
import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import TaskConfigurationError

SERVICES_FORMAT_IDENTIFIER = "mavai-services/1"
SERVICES_FILENAME = "mavai-services.yaml"

_DEFINITION_KEYS = {"type", "configuration", "variations"}
_CONFIGURATION_KEYS = {"system-prompt", "model", "temperature", "max-tokens"}

ENV_ENDPOINT = "MAVAI_LLM_ENDPOINT"
ENV_API_KEY = "MAVAI_LLM_API_KEY"
ENV_MODEL = "MAVAI_LLM_MODEL"


@dataclass(frozen=True, slots=True)
class LanguageModelParameters:
    """One language-model service configuration: its complete covariate values."""

    system_prompt: str
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """One service entry: its type's single, complete configuration."""

    name: str
    configuration: LanguageModelParameters


def _fail(message: str) -> TaskConfigurationError:
    return TaskConfigurationError(message)


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
    return ServiceDefinition(
        name=name,
        configuration=LanguageModelParameters(
            system_prompt=system_prompt,
            model=configuration.get("model"),
            temperature=configuration.get("temperature"),
            max_tokens=configuration.get("max-tokens"),
        ),
    )


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


def discover_services(task_path: Path) -> dict[str, ServiceDefinition]:
    """Load definitions from the conventional locations, nearest first."""
    for directory in (task_path.parent, Path.cwd()):
        candidate = directory / SERVICES_FILENAME
        if candidate.is_file():
            return parse_services(candidate.read_text(encoding="utf-8"))
    return {}


def resolved_provenance(parameters: LanguageModelParameters) -> dict[str, str]:
    """The provenance entries a definition-resolved run must carry."""
    entries = {
        "serviceType": "language-model",
        "systemPrompt": parameters.system_prompt,
        "model": parameters.model or os.environ.get(ENV_MODEL, ""),
    }
    if parameters.temperature is not None:
        entries["temperature"] = str(parameters.temperature)
    if parameters.max_tokens is not None:
        entries["maxTokens"] = str(parameters.max_tokens)
    return entries


def language_model_invoker(parameters: LanguageModelParameters) -> Callable[[str], str]:
    """Build the invocation callable for a language-model service.

    Speaks the OpenAI-compatible chat-completion protocol against the
    environment-configured endpoint. A transport failure or error response
    is a defect (the service was unreachable, not stochastic); an
    anticipated bad *answer* is simply the response, judged by the criteria.
    """
    endpoint = os.environ.get(ENV_ENDPOINT)
    if not endpoint:
        raise TaskConfigurationError(
            f"a language-model service needs the {ENV_ENDPOINT} environment variable "
            "(an OpenAI-compatible chat-completions endpoint)"
        )
    model = parameters.model or os.environ.get(ENV_MODEL)
    if not model:
        raise TaskConfigurationError(
            f"no model declared and {ENV_MODEL} is not set — declare `model:` in the "
            "service configuration or set the environment default"
        )
    api_key = os.environ.get(ENV_API_KEY, "")

    def invoke(user_prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": parameters.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if parameters.temperature is not None:
            payload["temperature"] = parameters.temperature
        if parameters.max_tokens is not None:
            payload["max_tokens"] = parameters.max_tokens
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("chat-completion response carried no text content")
        return content

    return invoke
