"""Parsing and validation: a contract file into a checked contract model.

Everything here happens at load time, before any invocation: structural
validation, reserved-key rejection with a pointer, the views block
(``raw`` reserved), subject/``path`` legality, per-input expectation
lists, and constructive refusals in format vocabulary.

The contract file is posture-free: the run mode (``test``/``measure``) is the
invocation verb, never a key.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ._errors import ContractConfigurationError

FORMAT_IDENTIFIER = "mavai-contract/1"
DEFAULT_CONFIDENCE = 0.95
RAW_VIEW = "raw"
STOCK_TRANSFORMS = {"json", "xml", "yaml"}

_TOP_LEVEL_KEYS = {
    "format",
    "contract",
    "service",
    "transforms",
    "inputs",
    "criteria",
    "intent",
    "confidence",
    "latency",
}
# `factors:` is deliberately absent from both sets: the explore grid lives in
# the services file, and the retired key fails the ordinary unknown-key check.
# `latency:` graduated from this set to a real key (a format amendment): a
# contract may assert per-percentile latency bounds, judged on test runs.
_RESERVED_TOP_LEVEL = {
    "facets",
    "covariates",
    "budget",
}
# Sample sizing is an invocation concern, withdrawn from the format: the
# contract carries the claim, the invocation carries the budget.
_WITHDRAWN_SIZING_KEYS = {
    "samples": (
        "`samples:` is not a contract key — the contract carries the claim, "
        "the invocation carries the budget. Size the run with `--samples N` "
        "(a test without it runs at the derived minimum; a measure requires it)"
    ),
    "samples-per-config": (
        "`samples-per-config:` is not a contract key — the contract carries "
        "the claim, the invocation carries the budget. Size the exploration "
        "with `--samples-per-config N` (default: 5 samples per configuration)"
    ),
}
_CRITERION_KEYS = {
    "name",
    "threshold",
    "threshold-origin",
    "contract-ref",
    "tolerate",
    "confidence",
    "postconditions",
    "equals",
    "one-of",
    "contains",
    "matches",
    "parses",
    "satisfies",
}
_FORM_KEYS = ("equals", "one-of", "contains", "matches", "parses", "satisfies")
_STRING_FORMS = ("equals", "one-of", "contains", "matches")
_SEAM_POINTER = (
    "reserved by the mavai contract format for a future version — see the format's "
    "extension seams documentation"
)


@dataclass(frozen=True, slots=True)
class FormDeclaration:
    """One postcondition form as declared: form key, argument, subject view, path."""

    form: str
    argument: Any
    view: str = RAW_VIEW
    path: str | None = None


@dataclass(frozen=True, slots=True)
class CriterionDeclaration:
    """One criterion entry as declared in the file.

    ``tolerate`` is an empirical criterion's sizing claim: the worst
    acceptable true pass rate, versioned with the claim it protects. It
    feeds risk-driven run sizing at test time and is meaningless alongside
    a declared ``threshold`` (a stipulated bar carries no baseline claim).
    ``confidence`` overrides the contract-level confidence for this
    criterion's derivation and judgement.
    """

    name: str
    forms: tuple[FormDeclaration, ...]
    threshold: float | None
    threshold_origin: str | None
    contract_ref: str | None
    tolerate: float | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class LatencyDeclaration:
    """The contract's ``latency:`` block as declared.

    Exactly one of ``ceilings`` / ``empirical`` is populated: explicit
    per-percentile millisecond ceilings, or the percentiles whose bounds
    are derived from a measured baseline at test time.
    """

    ceilings: tuple[tuple[str, int], ...]
    empirical: tuple[str, ...]
    confidence: float | None
    threshold_origin: str | None
    contract_ref: str | None


@dataclass(frozen=True, slots=True)
class ContractDeclaration:
    """The whole contract file, structurally validated. Posture-free by design."""

    contract: str
    service: str
    transforms: dict[str, str]
    inputs: tuple[str, ...]
    expected_pairs: tuple[tuple[str, tuple[FormDeclaration, ...]], ...]
    criteria: tuple[CriterionDeclaration, ...]
    intent: str
    confidence: float
    latency: LatencyDeclaration | None = None
    source_path: Path | None = field(default=None, compare=False)
    # Whether the file itself declared `confidence:` (as opposed to the
    # default applying) — interactive sizing asks only for what is missing.
    confidence_declared: bool = field(default=False, compare=False)


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


def _check_top_level_keys(data: dict[str, Any]) -> None:
    for key in data:
        if key == "kind":
            raise _fail(
                "`kind:` was withdrawn — the run mode is the invocation verb: "
                "`basel test contract.yaml` or `basel measure contract.yaml`"
            )
        if key in _WITHDRAWN_SIZING_KEYS:
            raise _fail(_WITHDRAWN_SIZING_KEYS[key])
        if key in _RESERVED_TOP_LEVEL:
            raise _fail(f"`{key}:` is {_SEAM_POINTER}")
        if key not in _TOP_LEVEL_KEYS:
            raise _fail(f"unknown key `{key}:` — not part of {FORMAT_IDENTIFIER}")
    for required in ("format", "contract", "service", "inputs", "criteria"):
        if required not in data:
            raise _fail(f"missing required key `{required}:`")
    if data["format"] != FORMAT_IDENTIFIER:
        raise _fail(f"`format:` must be {FORMAT_IDENTIFIER!r}, got {data['format']!r}")


def _parse_transforms(data: dict[str, Any]) -> dict[str, str]:
    if "transforms" not in data:
        return {}
    block = _require_mapping(data["transforms"], "`transforms:`")
    if not block:
        raise _fail("`transforms:` must be a non-empty mapping when declared")
    views: dict[str, str] = {}
    for view_name, transformation in block.items():
        if view_name == RAW_VIEW:
            raise _fail(
                "`raw` is the reserved name of the untransformed response and "
                "cannot be declared as a view"
            )
        if not isinstance(transformation, str) or not transformation:
            raise _fail(
                f"view {view_name!r}: the transformation must be a name — a stock "
                "one (json, xml, yaml) or a transformation registered in code"
            )
        views[view_name] = transformation
    return views


def _parse_form_entry(entry: dict[str, Any], where: str, views: dict[str, str]) -> FormDeclaration:
    keys = set(entry)
    view = RAW_VIEW
    path = None
    if "in" in keys:
        view_value = entry["in"]
        if not isinstance(view_value, str) or not view_value:
            raise _fail(f"{where}: `in:` must name a view")
        if view_value != RAW_VIEW and view_value not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(
                f"{where}: `in: {view_value}` names an undeclared view "
                f"(declared: {declared}; `raw` is always available)"
            )
        view = view_value
        keys.discard("in")
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
    if path is not None:
        if form not in _STRING_FORMS:
            raise _fail(f"{where}: `path:` qualifies the string forms only")
        if views.get(view) not in STOCK_TRANSFORMS:
            raise _fail(
                f"{where}: `path:` requires `in:` naming a view with a stock "
                "transformation (json, xml, or yaml)"
            )
    if form == "parses":
        target = entry[form]
        if view != RAW_VIEW:
            raise _fail(f"{where}: `parses:` takes no `in:` — it names its view directly")
        if not isinstance(target, str) or target not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(f"{where}: `parses:` references a declared view (declared: {declared})")
    return FormDeclaration(form=form, argument=entry[form], view=view, path=path)


def _parse_inputs(
    value: Any, views: dict[str, str]
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[FormDeclaration, ...]], ...]]:
    if not isinstance(value, list) or not value:
        raise _fail("`inputs:` must be a non-empty list")
    inputs: list[str] = []
    pairs: list[tuple[str, tuple[FormDeclaration, ...]]] = []
    for entry in value:
        if isinstance(entry, str):
            inputs.append(entry)
            continue
        if not (isinstance(entry, dict) and set(entry) == {"input", "expected"}):
            raise _fail("each `inputs:` entry is a string or an {input, expected} entry")
        input_value = entry["input"]
        if not isinstance(input_value, str):
            raise _fail("`input:` in an input/expected entry must be a string")
        where = f"expected for input {input_value!r}"
        expected = entry["expected"]
        if isinstance(expected, dict):
            expected = [expected]
        if not isinstance(expected, list) or not expected:
            raise _fail(f"{where}: `expected:` is a form or a non-empty list of forms")
        forms = tuple(
            _parse_form_entry(_require_mapping(form_entry, where), where, views)
            for form_entry in expected
        )
        for declaration in forms:
            if declaration.form == "parses":
                raise _fail(f"{where}: `parses:` is a criterion-level form")
        inputs.append(input_value)
        pairs.append((input_value, forms))
    return tuple(inputs), tuple(pairs)


def _parse_criterion(entry: Any, index: int, views: dict[str, str]) -> CriterionDeclaration:
    where = f"criteria entry {index + 1}"
    data = _require_mapping(entry, where)
    for key in data:
        if key in ("transform", "in"):
            raise _fail(
                f"{where}: `{key}:` does not belong on the criterion — declare views "
                "in the `transforms:` block and name a check's subject with `in:` on "
                "the check itself"
            )
        if key not in _CRITERION_KEYS and key != "path":
            raise _fail(f"{where}: unknown key `{key}:`")

    threshold = data.get("threshold")
    if threshold is not None:
        if threshold == "empirical":
            raise _fail(f"`threshold: empirical` is {_SEAM_POINTER}")
        if not isinstance(threshold, int | float) or not 0 < float(threshold) < 1:
            raise _fail(f"{where}: `threshold:` must be a number in (0, 1)")
        threshold = float(threshold)

    tolerate = data.get("tolerate")
    if tolerate is not None:
        if threshold is not None:
            raise _fail(
                f"{where}: `tolerate:` declares how far below the measured baseline "
                "a true rate may drop, so it belongs on an empirical criterion — a "
                "criterion with a declared `threshold:` has no baseline claim to "
                "protect; drop one of the two keys"
            )
        if not isinstance(tolerate, int | float) or not 0 < float(tolerate) < 1:
            raise _fail(f"{where}: `tolerate:` must be a number in (0, 1)")
        tolerate = float(tolerate)

    criterion_confidence = data.get("confidence")
    if criterion_confidence is not None:
        if (
            not isinstance(criterion_confidence, int | float)
            or not 0 < float(criterion_confidence) < 1
        ):
            raise _fail(f"{where}: `confidence:` must be a number in (0, 1)")
        criterion_confidence = float(criterion_confidence)

    forms: list[FormDeclaration] = []
    for form in _FORM_KEYS:
        if form in data:
            forms.append(_parse_form_entry({form: data[form]}, where, views))
    if "postconditions" in data:
        entries = data["postconditions"]
        if not isinstance(entries, list) or not entries:
            raise _fail(f"{where}: `postconditions:` must be a non-empty list")
        for form_entry in entries:
            forms.append(_parse_form_entry(_require_mapping(form_entry, where), where, views))

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
        threshold_origin=data.get("threshold-origin"),
        contract_ref=data.get("contract-ref"),
        tolerate=tolerate,
        confidence=criterion_confidence,
    )


_PERCENTILE_KEYS = ("p50", "p90", "p95", "p99")
_LATENCY_KEYS = {*_PERCENTILE_KEYS, "empirical", "confidence", "threshold-origin", "contract-ref"}


def _parse_latency(data: dict[str, Any]) -> LatencyDeclaration | None:
    """The ``latency:`` block: explicit millisecond ceilings, or empirical percentiles.

    Two mutually exclusive shapes::

        latency:            # explicit: SLA-style ceilings, in milliseconds
          p95: 500
          p99: 1500

        latency:            # empirical: bounds derived from the measured baseline
          empirical: [p95, p99]

    Either shape takes an optional ``confidence:`` (the derivation
    confidence for empirical bounds; recorded for explicit ones) and the
    provenance keys ``threshold-origin:`` / ``contract-ref:``.
    """
    if "latency" not in data:
        return None
    block = _require_mapping(data["latency"], "`latency:`")
    for key in block:
        if key not in _LATENCY_KEYS:
            supported = ", ".join(sorted(_LATENCY_KEYS))
            raise _fail(f"`latency:` has unknown key `{key}:` (supported: {supported})")

    ceilings: list[tuple[str, int]] = []
    for percentile in _PERCENTILE_KEYS:
        if percentile not in block:
            continue
        value = block[percentile]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _fail(
                f"`latency: {percentile}:` must be a positive whole number of "
                f"milliseconds, got {value!r}"
            )
        ceilings.append((percentile, value))

    empirical: tuple[str, ...] = ()
    if "empirical" in block:
        if ceilings:
            raise _fail(
                "`latency:` declares explicit ceilings and `empirical:` together — "
                "contradictory: a bound is either stipulated or derived from the "
                "measured baseline, not both"
            )
        entries = block["empirical"]
        if not isinstance(entries, list) or not entries:
            raise _fail("`latency: empirical:` must be a non-empty list of percentiles")
        for entry in entries:
            if entry not in _PERCENTILE_KEYS:
                supported = ", ".join(_PERCENTILE_KEYS)
                raise _fail(
                    f"`latency: empirical:` names unknown percentile {entry!r} "
                    f"(supported: {supported})"
                )
        if len(entries) != len(set(entries)):
            raise _fail("`latency: empirical:` names each percentile at most once")
        empirical = tuple(sorted(entries, key=_PERCENTILE_KEYS.index))

    if not ceilings and not empirical:
        raise _fail(
            "`latency:` declares no bounds — give explicit ceilings "
            "(`p95: 500`) or `empirical: [p95]`"
        )
    thresholds = [ms for _, ms in ceilings]
    if thresholds != sorted(thresholds):
        raise _fail(
            "`latency:` ceilings must be non-decreasing across percentiles — a "
            "tighter bound on a higher percentile contradicts itself"
        )

    confidence = block.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, int | float) or not 0 < float(confidence) < 1
    ):
        raise _fail("`latency: confidence:` must be a number in (0, 1)")

    origin = block.get("threshold-origin")
    if origin is not None and (not isinstance(origin, str) or not origin):
        raise _fail("`latency: threshold-origin:` must be a non-empty string")
    contract_ref = block.get("contract-ref")
    if contract_ref is not None and (not isinstance(contract_ref, str) or not contract_ref):
        raise _fail("`latency: contract-ref:` must be a non-empty string")

    return LatencyDeclaration(
        ceilings=tuple(ceilings),
        empirical=empirical,
        confidence=float(confidence) if confidence is not None else None,
        threshold_origin=origin,
        contract_ref=contract_ref,
    )


def parse_contract(text: str, source_path: Path | None = None) -> ContractDeclaration:
    """Parse and structurally validate a contract file's text.

    Raises:
        ContractConfigurationError: On any malformation, reserved construct,
            or contradiction — always before any invocation.
    """
    data = _require_mapping(_load_yaml(text), "the contract file")
    _check_top_level_keys(data)
    intent = data.get("intent", "verification")
    if intent not in ("verification", "smoke"):
        raise _fail(f"unknown `intent: {intent}` — expected verification or smoke")

    views = _parse_transforms(data)
    inputs, expected_pairs = _parse_inputs(data["inputs"], views)

    criteria_value = data["criteria"]
    if not isinstance(criteria_value, list) or not criteria_value:
        raise _fail("`criteria:` must be a non-empty list of criterion entries")
    criteria = tuple(
        _parse_criterion(entry, index, views) for index, entry in enumerate(criteria_value)
    )
    names = [criterion.name for criterion in criteria]
    if len(names) != len(set(names)):
        raise _fail("criterion names must be unique within the contract")
    if expected_pairs and len(criteria) != 1:
        raise _fail(
            "per-input `expected:` entries require exactly one criteria entry — with "
            "several criteria their owner would be ambiguous; move the expectations "
            "into the criterion entries"
        )
    if not any(c.forms for c in criteria) and not expected_pairs:
        raise _fail("every criterion declares at least one postcondition form")

    confidence = data.get("confidence", DEFAULT_CONFIDENCE)
    if not isinstance(confidence, int | float) or not 0 < float(confidence) < 1:
        raise _fail("`confidence:` must be a number in (0, 1)")

    return ContractDeclaration(
        contract=_require_string(data, "contract"),
        service=_require_string(data, "service"),
        transforms=views,
        inputs=inputs,
        expected_pairs=expected_pairs,
        criteria=criteria,
        intent=intent,
        confidence=float(confidence),
        latency=_parse_latency(data),
        source_path=source_path,
        confidence_declared="confidence" in data,
    )


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise _fail(f"`{key}:` must be a non-empty string")
    return value


def load_contract(path: Path) -> ContractDeclaration:
    """Read and parse a contract file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _fail(f"cannot read contract file {path}: {error}") from error
    return parse_contract(text, source_path=path)
