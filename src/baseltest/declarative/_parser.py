"""Parsing and validation: a task file into a checked task model.

Everything here happens at load time, before any invocation: structural
validation, reserved-key rejection with a pointer, the run-kind
contradiction, transform/parses exclusivity, path legality, and eager
compilation of selection expressions.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import TaskConfigurationError

FORMAT_IDENTIFIER = "mavai-task/1"
DEFAULT_CONFIDENCE = 0.95

_TOP_LEVEL_KEYS = {
    "format",
    "task",
    "service",
    "samples",
    "inputs",
    "criteria",
    "intent",
    "confidence",
    "kind",
}
_RESERVED_TOP_LEVEL = {
    "facets",
    "factors",
    "samples-per-config",
    "covariates",
    "latency",
    "budget",
}
_RESERVED_KINDS = {"explore", "optimize"}
_CRITERION_KEYS = {
    "name",
    "threshold",
    "threshold-origin",
    "contract-ref",
    "transform",
    "postconditions",
    "equals",
    "one-of",
    "contains",
    "matches",
    "parses",
    "satisfies",
}
_FORM_KEYS = ("equals", "one-of", "contains", "matches", "parses", "satisfies")
_STOCK_TRANSFORMS = {"json", "xml", "yaml"}
_SEAM_POINTER = (
    "reserved by the mavai task format for a future version — see the format's "
    "extension seams documentation"
)


@dataclass(frozen=True, slots=True)
class FormDeclaration:
    """One postcondition form as declared: the form key, its argument, optional path."""

    form: str
    argument: Any
    path: str | None = None


@dataclass(frozen=True, slots=True)
class CriterionDeclaration:
    """One criterion entry as declared in the file."""

    name: str
    forms: tuple[FormDeclaration, ...]
    threshold: float | None
    transform: str | None
    parses: str | None
    threshold_origin: str | None
    contract_ref: str | None


@dataclass(frozen=True, slots=True)
class TaskDeclaration:
    """The whole task file, structurally validated."""

    task: str
    service: str
    samples: int | None
    inputs: tuple[str, ...]
    expected_pairs: tuple[tuple[str, FormDeclaration], ...]
    criteria: tuple[CriterionDeclaration, ...]
    intent: str
    confidence: float
    kind: str | None
    source_path: Path | None = field(default=None, compare=False)


def _fail(message: str) -> "TaskConfigurationError":
    return TaskConfigurationError(message)


def _load_yaml(text: str) -> Any:
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    try:
        return yaml.load(io.StringIO(text))
    except YAMLError as error:
        raise _fail(f"the task file is not well-formed YAML: {error}") from error


def _require_mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{what} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise _fail(f"{what} has a non-string key: {key!r}")
    return value


def _check_top_level_keys(data: dict[str, Any]) -> None:
    for key in data:
        if key in _RESERVED_TOP_LEVEL:
            raise _fail(f"`{key}:` is {_SEAM_POINTER}")
        if key not in _TOP_LEVEL_KEYS:
            raise _fail(f"unknown key `{key}:` — not part of {FORMAT_IDENTIFIER}")
    for required in ("format", "task", "service", "inputs", "criteria"):
        if required not in data:
            raise _fail(f"missing required key `{required}:`")
    if data["format"] != FORMAT_IDENTIFIER:
        raise _fail(f"`format:` must be {FORMAT_IDENTIFIER!r}, got {data['format']!r}")


def _parse_kind_and_intent(data: dict[str, Any]) -> tuple[str | None, str]:
    kind = data.get("kind")
    if kind is not None:
        if kind in _RESERVED_KINDS:
            raise _fail(f"`kind: {kind}` is {_SEAM_POINTER}")
        if kind not in ("test", "measure"):
            raise _fail(f"unknown `kind: {kind}` — expected test or measure")
    intent = data.get("intent", "verification")
    if intent not in ("verification", "smoke"):
        raise _fail(f"unknown `intent: {intent}` — expected verification or smoke")
    return kind, intent


def _parse_inputs(
    value: Any,
) -> tuple[tuple[str, ...], tuple[tuple[str, FormDeclaration], ...]]:
    if not isinstance(value, list) or not value:
        raise _fail("`inputs:` must be a non-empty list")
    inputs: list[str] = []
    pairs: list[tuple[str, FormDeclaration]] = []
    for entry in value:
        if isinstance(entry, str):
            inputs.append(entry)
        elif isinstance(entry, dict) and set(entry) == {"input", "expected"}:
            input_value = entry["input"]
            if not isinstance(input_value, str):
                raise _fail("`input:` in an input/expected pair must be a string")
            expected = _require_mapping(entry["expected"], "`expected:`")
            if len(expected) != 1:
                raise _fail("`expected:` declares exactly one postcondition form")
            form, argument = next(iter(expected.items()))
            if form not in ("equals", "one-of", "contains", "matches"):
                raise _fail(f"`expected:` does not support the `{form}` form")
            inputs.append(input_value)
            pairs.append((input_value, FormDeclaration(form=form, argument=argument)))
        else:
            raise _fail("each `inputs:` entry is a string or an {input, expected} pair")
    return tuple(inputs), tuple(pairs)


def _parse_form_entry(entry: dict[str, Any], where: str) -> FormDeclaration:
    keys = set(entry)
    path = None
    if "path" in keys:
        path_value = entry["path"]
        if not isinstance(path_value, str) or not path_value:
            raise _fail(f"{where}: `path:` must be a non-empty string")
        path = path_value
        keys.discard("path")
    if len(keys) != 1:
        raise _fail(f"{where}: each postcondition declares exactly one form")
    form = keys.pop()
    if form not in _FORM_KEYS:
        raise _fail(f"{where}: unknown postcondition form `{form}`")
    if path is not None and form in ("parses", "satisfies"):
        raise _fail(f"{where}: `path:` qualifies the string forms only")
    return FormDeclaration(form=form, argument=entry[form], path=path)


def _parse_criterion(entry: Any, index: int) -> CriterionDeclaration:
    where = f"criteria entry {index + 1}"
    data = _require_mapping(entry, where)
    for key in data:
        if key not in _CRITERION_KEYS and key != "path":
            raise _fail(f"{where}: unknown key `{key}:`")

    threshold = data.get("threshold")
    if threshold is not None:
        if threshold == "empirical":
            raise _fail(f"`threshold: empirical` is {_SEAM_POINTER}")
        if not isinstance(threshold, int | float) or not 0 < float(threshold) < 1:
            raise _fail(f"{where}: `threshold:` must be a number in (0, 1)")
        threshold = float(threshold)

    transform_name = data.get("transform")
    parses = data.get("parses")
    if transform_name is not None and parses is not None:
        raise _fail(
            f"{where}: declare at most one of `transform:` and `parses:` "
            "(`parses:` is shorthand for a transform with no value-consumers)"
        )
    if parses is not None and parses not in _STOCK_TRANSFORMS:
        raise _fail(f"{where}: `parses:` supports json, xml, or yaml")
    if transform_name is not None and (not isinstance(transform_name, str) or not transform_name):
        raise _fail(f"{where}: `transform:` must be a non-empty name")

    forms: list[FormDeclaration] = []
    inline_forms = [key for key in _FORM_KEYS if key in data]
    for form in inline_forms:
        forms.append(FormDeclaration(form=form, argument=data[form], path=None))
    if "postconditions" in data:
        entries = data["postconditions"]
        if not isinstance(entries, list) or not entries:
            raise _fail(f"{where}: `postconditions:` must be a non-empty list")
        for form_entry in entries:
            forms.append(_parse_form_entry(_require_mapping(form_entry, where), where))

    effective_transform = transform_name or parses
    for declaration in forms:
        if declaration.path is not None and (effective_transform not in _STOCK_TRANSFORMS):
            raise _fail(
                f"{where}: `path:` requires a stock transform "
                "(`transform: json`, `xml`, or `yaml`) on the criterion"
            )

    name = data.get("name")
    if name is None:
        source = forms[0].form if forms else "criterion"
        name = f"criterion-{index + 1}-{source}"
    if not isinstance(name, str) or not name:
        raise _fail(f"{where}: `name:` must be a non-empty string")

    return CriterionDeclaration(
        name=name,
        forms=tuple(forms),
        threshold=threshold,
        transform=transform_name,
        parses=parses,
        threshold_origin=data.get("threshold-origin"),
        contract_ref=data.get("contract-ref"),
    )


# javai-ref: JVI-E2WH9DE — do not remove (resolves in javai-orchestrator)
def parse_task(text: str, source_path: Path | None = None) -> TaskDeclaration:
    """Parse and structurally validate a task file's text.

    Raises:
        TaskConfigurationError: On any malformation, reserved construct,
            or contradiction — always before any invocation.
    """
    data = _require_mapping(_load_yaml(text), "the task file")
    _check_top_level_keys(data)
    kind, intent = _parse_kind_and_intent(data)
    inputs, expected_pairs = _parse_inputs(data["inputs"])

    criteria_value = data["criteria"]
    if not isinstance(criteria_value, list) or not criteria_value:
        raise _fail("`criteria:` must be a non-empty list of criterion entries")
    criteria = tuple(_parse_criterion(entry, index) for index, entry in enumerate(criteria_value))
    names = [criterion.name for criterion in criteria]
    if len(names) != len(set(names)):
        raise _fail("criterion names must be unique within the task")
    if expected_pairs and len(criteria) != 1:
        raise _fail(
            "per-input `expected:` pairs require exactly one criteria entry — with "
            "several criteria their owner would be ambiguous; move the expectations "
            "into the criterion entries"
        )
    if not any(c.forms for c in criteria) and not expected_pairs:
        raise _fail("every criterion declares at least one postcondition form")

    samples = data.get("samples")
    if samples is not None and (not isinstance(samples, int) or samples <= 0):
        raise _fail("`samples:` must be a positive integer")

    confidence = data.get("confidence", DEFAULT_CONFIDENCE)
    if not isinstance(confidence, int | float) or not 0 < float(confidence) < 1:
        raise _fail("`confidence:` must be a number in (0, 1)")

    thresholded = any(c.threshold is not None for c in criteria)
    if kind == "test" and not thresholded:
        raise _fail(
            "`kind: test` requires at least one criterion to declare a `threshold:` "
            "— a test needs a bar; without one, run the task as a measurement"
        )
    if samples is None and not thresholded:
        raise _fail(
            "`samples:` is required when no criterion declares a `threshold:` — an "
            "observation has no feasibility anchor to derive a sample count from"
        )

    return TaskDeclaration(
        task=_require_string(data, "task"),
        service=_require_string(data, "service"),
        samples=samples,
        inputs=inputs,
        expected_pairs=expected_pairs,
        criteria=criteria,
        intent=intent,
        confidence=float(confidence),
        kind=kind,
        source_path=source_path,
    )


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise _fail(f"`{key}:` must be a non-empty string")
    return value


def load_task(path: Path) -> TaskDeclaration:
    """Read and parse a task file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _fail(f"cannot read task file {path}: {error}") from error
    return parse_task(text, source_path=path)
