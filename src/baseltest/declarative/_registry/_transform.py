"""Transform registration: the record, its schema loading, the stock vocabulary.

`TransformRegistration` is one registered transformation and its declared
output shape; `_loaded_schema` resolves and vets a declared schema (a mapping
or a path to a schema file); `_STOCK_TRANSFORMS` is the stock-transform
vocabulary the registry reserves, single-sourced from `_structured`.
"""

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .._errors import ContractConfigurationError
from .._structured import STOCK_TRANSFORMS

_STOCK_TRANSFORMS = tuple(STOCK_TRANSFORMS)


@dataclass(frozen=True, slots=True)
class TransformRegistration:
    """One registered transformation: the callable and its declared shape.

    Attributes:
        fn: The transformation callable.
        output_schema: The declared JSON Schema of the transformation's
            output, when declared — enables static ``path:`` validation
            at load time and always-on per-trial output validation.
        fingerprint: The canonical sha256 fingerprint of the declared
            schema, recorded descriptively in baseline artefacts (an
            output schema executes after the response exists and has no
            influence on the service's behaviour, so it is never a
            covariate); ``None`` when no schema is declared.
    """

    fn: Callable[[str], Any]
    output_schema: dict[str, Any] | None = None
    fingerprint: str | None = None


def _loaded_schema(name: str, output_schema: Any) -> dict[str, Any]:
    """Resolve the declared schema (mapping, or path to a schema file) and vet it."""
    schema = output_schema
    if isinstance(schema, (str, PurePath)):
        path = Path(schema)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ContractConfigurationError(
                f"transform {name!r}: cannot read output schema file {path}: {error}"
            ) from error
        try:
            if path.suffix.lower() in (".yaml", ".yml"):
                yaml = YAML(typ="safe", pure=True)
                schema = yaml.load(io.StringIO(text))
            else:
                schema = json.loads(text)
        except (ValueError, YAMLError) as error:
            raise ContractConfigurationError(
                f"transform {name!r}: output schema file {path} does not parse: {error}"
            ) from error
    if not isinstance(schema, dict):
        raise ContractConfigurationError(
            f"transform {name!r}: `output_schema` must be a mapping (the JSON Schema "
            f"of the transformation's output) or a path to a schema file, got "
            f"{type(schema).__name__}"
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ContractConfigurationError(
            f"transform {name!r}: the declared output schema is not a valid JSON "
            f"Schema: {error.message}"
        ) from error
    return schema
