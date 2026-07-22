"""Disclosure rendering: the plain-language and machine-readable sizing blocks.

The single-claim explanation sentence, the multi-criterion aligned table,
and the JSON payload — all priced at the actual run size. These format
already-computed claims; the statistics they read (floor, power, detectable
drop) are pure functions of the claim and the size.
"""

from baseltest.statistics import detectable_rate, power_at, wilson_lower_bound_from_rate

from ._model import SizingClaim
from ._rates import _percent


def _explanation(
    claim: SizingClaim, samples: int, *, governing: bool, several: bool, only_catch: bool = False
) -> str:
    """The plain-language explanation sentence, at the actual run size."""
    floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
    power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
    prefix = f"criterion {claim.criterion}: " if several else ""
    suffix = " (this criterion set the run size)" if governing and several else ""
    verb = "only catch" if only_catch else "catch"
    return (
        f"{prefix}If this test passes, you can be {_percent(claim.confidence)} confident "
        f"the true pass rate is at least {_percent(floor)}. This design will {verb} a "
        f"genuine drop to {_percent(claim.tolerated_rate)} about {_percent(power)} of "
        f"the time.{suffix}"
    )


def _sizing_table(claims: list[SizingClaim], samples: int, governing: str) -> list[str]:
    """The multi-criterion sizing block as one aligned table: a row per
    claim, priced at the governing run size, the governing row marked."""
    headers = (
        "criterion",
        "tolerates",
        "confidence",
        "drop caught",
        "a pass proves",
        "needs alone",
    )
    rows = []
    for claim in claims:
        floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
        power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
        rows.append(
            (
                claim.criterion,
                _percent(claim.tolerated_rate),
                _percent(claim.confidence),
                f"about {_percent(power)}",
                f"at least {_percent(floor)}",
                str(claim.required_n or 0),
            )
        )
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    lines = ["  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    for claim, row in zip(claims, rows, strict=True):
        cells = [row[0].ljust(widths[0])]
        cells.extend(row[i].rjust(widths[i]) for i in range(1, len(headers)))
        line = "  " + "  ".join(cells)
        if claim.criterion == governing:
            line += "  ← sets the run size"
        lines.append(line.rstrip())
    return lines


def _json_payload(
    claims: list[SizingClaim],
    samples: int,
    governing: str | None,
    explanations: list[str],
) -> dict[str, object]:
    """The machine-readable sizing block: per-criterion array, governing
    summary, and the flat single-criterion convenience fields."""
    criteria = []
    for claim in claims:
        floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
        power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
        criteria.append(
            {
                "criterion": claim.criterion,
                "baseline_rate": claim.baseline_rate,
                "tolerated_rate": claim.tolerated_rate,
                "confidence": claim.confidence,
                "required_n": claim.required_n,
                "floor": floor,
                "power": power,
            }
        )
    lead = next((c for c in claims if c.criterion == governing), claims[0])
    lead_row = next(row for row in criteria if row["criterion"] == lead.criterion)
    return {
        "approach": "confidence-first (risk-driven)",
        "criteria": criteria,
        "governing": {"criterion": governing, "samples": samples},
        "baseline": lead.baseline_rate,
        "confidence": lead.confidence,
        "tolerableRate": lead.tolerated_rate,
        "targetPower": lead.target_power,
        "requiredSamples": lead.required_n,
        "acceptanceFloor": lead_row["floor"],
        "detectableDrop": detectable_rate(
            samples, lead.baseline_rate, lead.confidence, lead.target_power
        ),
        "explanation": "\n".join(explanations),
    }
