"""Stock transforms and path-qualified checks: the structured-response machinery.

Implements the format's pinned standards: RFC 9535 JSONPath for ``json``
(and for ``yaml``, over its JSON-model projection), XPath 1.0 for ``xml``.
Selection semantics: an empty selection is a failed trial with its own
reason; a non-empty selection requires every selected value to satisfy the
form; scalars compare by content (strings) or by their JSON text (numbers,
booleans, null); selecting a JSON object or array under a string form is a
per-trial type failure — structure is selected through, not compared as
text.
"""

import io
import json
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from typing import Any

import elementpath
import jsonpath_rfc9535
from elementpath.xpath1 import XPath1Parser
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from baseltest.contract import Postcondition, PostconditionResult, TransformError

from ._errors import TaskConfigurationError

_YAML_NODE_BUDGET = 1_000_000


def json_transform(raw: str) -> Any:
    """Stock ``transform: json``."""
    try:
        return json.loads(raw)
    except ValueError as error:
        raise TransformError(f"response does not parse as json: {error}") from error


def xml_transform(raw: str) -> ElementTree.Element:
    """Stock ``transform: xml``."""
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise TransformError(f"response does not parse as xml: {error}") from error


def _check_yaml_projection(value: Any, budget: list[int]) -> None:
    """Enforce the JSON-model projection rules and the expansion budget."""
    budget[0] -= 1
    if budget[0] <= 0:
        raise TransformError("yaml document exceeds the expansion budget")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TransformError(
                    f"yaml mapping key {key!r} is not a string; the document does "
                    "not project into the JSON data model"
                )
            _check_yaml_projection(item, budget)
    elif isinstance(value, list):
        for item in value:
            _check_yaml_projection(item, budget)
    elif value is not None and not isinstance(value, str | int | float | bool):
        raise TransformError(f"yaml value of type {type(value).__name__} has no JSON-model image")


def yaml_transform(raw: str) -> Any:
    """Stock ``transform: yaml``: YAML 1.2 Core Schema, projected to the JSON model.

    Safe construction only; a multi-document stream, a non-core tag, a
    non-string mapping key, or an expansion beyond the budget is a failed
    trial.
    """
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        value = yaml.load(io.StringIO(raw))
    except YAMLError as error:
        raise TransformError(f"response does not parse as yaml: {error}") from error
    _check_yaml_projection(value, [_YAML_NODE_BUDGET])
    return value


STOCK_TRANSFORMS: dict[str, Callable[[str], Any]] = {
    "json": json_transform,
    "xml": xml_transform,
    "yaml": yaml_transform,
}


def _json_scalar_text(value: Any) -> str | None:
    """The comparison text of a selected JSON-model value; None for structure."""
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    return None


def compile_jsonpath(expression: str, where: str) -> Any:
    """Compile a JSONPath expression eagerly; a bad expression is a load-time refusal."""
    try:
        return jsonpath_rfc9535.compile(expression)
    except Exception as error:
        raise TaskConfigurationError(
            f"{where}: `path: {expression}` is not a valid JSONPath (RFC 9535) expression: {error}"
        ) from error


def compile_xpath(expression: str, where: str) -> Any:
    """Validate an XPath 1.0 expression eagerly; a bad expression is a load-time refusal."""
    try:
        elementpath.Selector(expression, parser=XPath1Parser)
    except Exception as error:
        raise TaskConfigurationError(
            f"{where}: `path: {expression}` is not a valid XPath 1.0 expression: {error}"
        ) from error
    return expression


def _xpath_values(document: Any, expression: str) -> list[str]:
    """Selected values as XPath 1.0 string projections."""
    selected = elementpath.select(document, expression, parser=XPath1Parser)
    if not isinstance(selected, list):
        selected = [selected]
    values: list[str] = []
    for item in selected:
        if isinstance(item, ElementTree.Element):
            values.append("".join(item.itertext()))
        elif isinstance(item, bool):
            values.append("true" if item else "false")
        elif isinstance(item, float) and item.is_integer():
            values.append(str(int(item)))
        else:
            values.append(str(item))
    return values


def path_qualified(
    language: str,
    expression: str,
    compiled: Any,
    inner: Postcondition,
) -> Postcondition:
    """Wrap a string-form postcondition to judge the values a path selects.

    ``language`` is ``"jsonpath"`` (for json and yaml transforms) or
    ``"xpath"``. The wrapped check applies the inner form to every selected
    value's string projection; empty selections and structural values under
    a string form are per-trial failures with their own reasons.
    """

    def check(_raw: str, value: Any) -> PostconditionResult:
        if language == "jsonpath":
            selected = [node.value for node in compiled.find(value)]
            texts: list[str] = []
            for item in selected:
                text = _json_scalar_text(item)
                if text is None:
                    return PostconditionResult.failed(
                        f"path {expression} selected a {type(item).__name__}, not a "
                        "scalar — a string form cannot compare structure"
                    )
                texts.append(text)
        else:
            texts = _xpath_values(value, expression)
        if not texts:
            return PostconditionResult.failed(f"path {expression} selected nothing")
        for text in texts:
            result = inner.evaluate(text, text)
            if not result.passed:
                return PostconditionResult.failed(f"path {expression}: {result.reason}")
        return PostconditionResult.ok()

    return Postcondition(name=f"{inner.name} at {expression}", check=check)
