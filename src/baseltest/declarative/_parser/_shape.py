"""Low-level shape helpers shared across the section parsers.

The failure constructor, the YAML load, the mapping/string shape checks,
and the reserved-seam message fragment.
"""

import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .._errors import ContractConfigurationError

_SEAM_POINTER = (
    "reserved by the mavai contract format for a future version — see the format's "
    "extension seams documentation"
)


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


def _load_yaml(text: str) -> Any:
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        return yaml.load(io.StringIO(text))
    except YAMLError as error:
        raise _fail(f"the contract file is not well-formed YAML: {error}") from error


def _require_mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{what} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise _fail(f"{what} has a non-string key: {key!r}")
    return value


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise _fail(f"`{key}:` must be a non-empty string")
    return value
