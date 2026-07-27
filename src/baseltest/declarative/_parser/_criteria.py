"""The ``criteria:`` block: one criterion entry into a CriterionDeclaration.

Key allowlist (with the misplaced-``transform``/``in`` refusals), the
``threshold``/``tolerate``/``confidence`` value checks, the inline and
``postconditions:`` forms, and the derived default name.
"""

import re
from decimal import Decimal
from typing import Any

from ._forms import _FORM_KEYS, _parse_form_entry
from ._model import CriterionDeclaration, FormDeclaration
from ._shape import _SEAM_POINTER, _fail, _require_mapping

# The bar-provenance categories are a closed set: an unknown origin is
# refused, never silently admitted as a new category.
THRESHOLD_ORIGINS = ("sla", "slo", "policy")

# Direct criterion-level forms judge raw, so the collective set forms —
# which require `in:` + `path:` — are absent here by design: at criterion
# level they fail the ordinary unknown-key check, as in the format schema.
_CRITERION_KEYS = {
    "name",
    "threshold",
    "threshold-origin",
    "contract-ref",
    "tolerate",
    "confidence",
    "optional-slack",
    "postconditions",
    "equals",
    "one-of",
    "contains",
    "matches",
    "parses",
    "satisfies",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "not-equals",
    "equals-ci",
    "is-null",
    "is",
}


def _parse_criterion(entry: Any, index: int, views: dict[str, str]) -> CriterionDeclaration:
    where = f"criteria entry {index + 1}"
    data = _require_mapping(entry, where)
    for key in data:
        if key in ("transform", "in", "path"):
            raise _fail(
                f"{where}: `{key}:` does not belong on the criterion — declare views "
                "in the `transforms:` block and qualify a check's subject with `in:` "
                "and `path:` on the check itself"
            )
        if key not in _CRITERION_KEYS:
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
        if threshold is not None:
            raise _fail(
                f"{where}: `confidence:` on a criterion belongs to an empirical "
                "criterion — a criterion with a declared `threshold:` uses the "
                "contract-level confidence; drop one of the two keys"
            )
        if (
            not isinstance(criterion_confidence, int | float)
            or not 0 < float(criterion_confidence) < 1
        ):
            raise _fail(f"{where}: `confidence:` must be a number in (0, 1)")
        criterion_confidence = float(criterion_confidence)

    optional_slack = _parse_optional_slack(data.get("optional-slack"), where)

    origin = data.get("threshold-origin")
    if origin is not None and origin not in THRESHOLD_ORIGINS:
        raise _fail(
            f"{where}: `threshold-origin:` names the bar's provenance category — "
            f"one of {', '.join(THRESHOLD_ORIGINS)} — got {origin!r}"
        )

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
        optional_slack=optional_slack,
    )


_PERCENT_SLACK = re.compile(r"^([0-9]+(?:\.[0-9]+)?)%$")


def _parse_optional_slack(value: Any, where: str) -> int | Decimal | None:
    """The optional-check failure budget: a count, or an explicit percentage.

    The ``%`` suffix is the disambiguator — ``2`` is always a count, ``"2%"``
    always a fraction of the applicable optional checks (resolved by floor at
    evaluation time). A bare fraction, a negative value, or a non-integer
    count is refused, never guessed at.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str):
        match = _PERCENT_SLACK.match(value.strip())
        if match:
            return Decimal(match.group(1))
    raise _fail(
        f"{where}: `optional-slack:` takes a non-negative whole count of optional "
        f"checks that may fail, or an explicit percentage like `20%` — got {value!r} "
        "(a bare fraction is never guessed at)"
    )
