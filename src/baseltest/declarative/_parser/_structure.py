"""Top-level document structure: the key allowlist/withdrawals and transforms.

The top-level key check (unknown keys, withdrawn sizing keys, reserved
seams, required keys, the ``format:`` identifier) and the ``transforms:``
block, whose ``raw`` name is reserved.
"""

from typing import Any

from ._model import FORMAT_IDENTIFIER, RAW_VIEW
from ._shape import _SEAM_POINTER, _fail, _require_mapping

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
