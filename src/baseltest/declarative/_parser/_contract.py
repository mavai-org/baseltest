"""The contract parser: assemble the validated sections into a ContractDeclaration.

``parse_contract`` orchestrates the section parsers and the cross-section
checks (unique criterion names, per-input expectations require a single
criterion, every criterion carries a form); ``load_contract`` reads the
file from disk. Everything here happens at load time, before any invocation.
"""

from dataclasses import replace
from pathlib import Path

from baseltest.engine import Intent
from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL

from .._roots import Roots
from ._criteria import _parse_criterion
from ._inputs import _parse_inputs
from ._latency import _parse_latency
from ._model import ContractDeclaration, CriterionDeclaration, Form, FormDeclaration
from ._shape import _fail, _load_yaml, _require_mapping, _require_string
from ._structure import _check_top_level_keys, _parse_transforms


# mavai-ref: JVI-7WE7H84 — do not remove (resolves in mavai-orchestrator)
def _default_anchor(criterion: CriterionDeclaration, views: dict[str, str]) -> str | None:
    """The criterion's default subject view, or None when nothing anchors it.

    The path-conditional default (subject rule, 2026-07-27): the view named
    by the criterion's single ``parses:`` form wins — an explicit statement
    of the canonical view; several ``parses:`` forms name no single anchor
    and fall through. Failing that, a contract with exactly one declared
    transform has only one structured view a ``path:`` could mean. A second
    transform makes the omission a refusal, loud — never a silent guess.
    """
    parse_views = [str(form.argument) for form in criterion.forms if form.form is Form.PARSES]
    if len(parse_views) == 1:
        return parse_views[0]
    if len(views) == 1:
        return next(iter(views))
    return None


def _resolve_form(form: FormDeclaration, anchor: str | None, where: str) -> FormDeclaration:
    if form.view is not None:
        return form
    if anchor is None:
        raise _fail(
            f"{where}: `{form.form}:` carries `path:` but omits `in:` and no default "
            "view is resolvable — add `in:` naming a declared view, or declare "
            "`parses:` on the criterion"
        )
    return replace(form, view=anchor)


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
    # Named path anchors: resolve the block before inputs parse (the
    # file-referencing positions consume it), refuse dead declarations
    # after (usage coherence is a whole-file property).
    roots = Roots.parse(data.get("roots"), base_dir, "the contract file")
    inputs, expected_pairs = _parse_inputs(data["inputs"], views, base_dir, roots)
    roots.refuse_dead()

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
    for criterion in criteria:
        if not criterion.forms:
            raise _fail(
                f"criterion {criterion.name!r} declares no postcondition form — "
                "every criterion declares at least one form of its own; per-input "
                "`expected:` entries supplement a criterion's forms, never replace them"
            )

    # Resolve the path-conditional default subject: every form that omitted
    # `in:` beside `path:` inherits its owning criterion's anchor. Per-input
    # expectations belong to the single criterion (enforced above), so they
    # share its anchor. After this pass no declaration carries an
    # unresolved subject — instantiation and view validation see a resolved
    # view exactly as if `in:` had been spelled.
    criteria = tuple(
        replace(
            criterion,
            forms=tuple(
                _resolve_form(
                    form, _default_anchor(criterion, views), f"criterion {criterion.name}"
                )
                for form in criterion.forms
            ),
        )
        for criterion in criteria
    )
    if expected_pairs:
        anchor = _default_anchor(criteria[0], views)
        expected_pairs = tuple(
            (
                input_index,
                input_value,
                tuple(
                    _resolve_form(form, anchor, f"expected for input {input_index}")
                    for form in declarations
                ),
            )
            for input_index, input_value, declarations in expected_pairs
        )

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
        roots=roots.disclosures(),
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
