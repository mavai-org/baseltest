"""The ``latency:`` block: explicit millisecond ceilings, or empirical percentiles.

Two mutually exclusive shapes — SLA-style per-percentile ceilings, or the
percentiles whose bounds derive from a measured baseline — each with an
optional ``confidence:`` and the provenance keys.
"""

from typing import Any

from baseltest.contract import PERCENTILE_LEVELS

from ._model import LatencyDeclaration
from ._shape import _fail, _require_mapping

_PERCENTILE_KEYS = tuple(PERCENTILE_LEVELS)
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
