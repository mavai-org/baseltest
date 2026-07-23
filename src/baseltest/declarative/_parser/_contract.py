"""The contract parser: assemble the validated sections into a ContractDeclaration.

``parse_contract`` orchestrates the section parsers and the cross-section
checks (unique criterion names, per-input expectations require a single
criterion, every criterion carries a form); ``load_contract`` reads the
file from disk. Everything here happens at load time, before any invocation.
"""

from pathlib import Path

from baseltest.engine import Intent
from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL

from ._criteria import _parse_criterion
from ._inputs import _parse_inputs
from ._latency import _parse_latency
from ._model import ContractDeclaration
from ._shape import _fail, _load_yaml, _require_mapping, _require_string
from ._structure import _check_top_level_keys, _parse_transforms


def parse_contract(text: str, source_path: Path | None = None) -> ContractDeclaration:
    """Parse and structurally validate a contract file's text.

    Raises:
        ContractConfigurationError: On any malformation, reserved construct,
            or contradiction — always before any invocation.
    """
    data = _require_mapping(_load_yaml(text), "the contract file")
    _check_top_level_keys(data)
    intent_raw = data.get("intent", Intent.VERIFICATION.value)
    try:
        intent = Intent(intent_raw)
    except ValueError:
        raise _fail(f"unknown `intent: {intent_raw}` — expected verification or smoke") from None

    views = _parse_transforms(data)
    base_dir = source_path.parent if source_path is not None else None
    inputs, expected_pairs = _parse_inputs(data["inputs"], views, base_dir)

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

    confidence = data.get("confidence", DEFAULT_CONFIDENCE_LEVEL)
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


def load_contract(path: Path) -> ContractDeclaration:
    """Read and parse a contract file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _fail(f"cannot read contract file {path}: {error}") from error
    return parse_contract(text, source_path=path)
