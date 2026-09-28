"""Disclosure rendering: the plain-language and machine-readable sizing blocks.

The single-claim explanation sentence, the multi-criterion aligned table,
and the JSON payload — all priced at the actual run size against the
observed baseline. These format already-priced claims; the statistics they
read (the cutoff, the resolved power, the rate the size can reliably catch)
are pure functions of the claim and the size.
"""

from baseltest.statistics import fisher_cutoff, resolved_detectable_rate, resolved_power

from ._model import SizingClaim, _UnsizeableCriterion
from ._rates import _percent


def _nothing_to_defend(unsizeable: list[_UnsizeableCriterion]) -> str:
    """Why a run cannot be sized against a baseline that passed nothing.

    Reads as a fact about the measurement, because that is what it is. It
    names every offending criterion rather than the first: a reader who
    fixes the one they were told about and meets the same refusal has been
    told the truth twice and helped once.
    """
    named = "\n".join(
        f"  {criterion.name} — passed on 0 of {criterion.trials} baseline samples"
        for criterion in unsizeable
    )
    subject = "criterion" if len(unsizeable) == 1 else "criteria"
    return (
        f"cannot size the run — the baseline records no successes for this {subject}:\n"
        f"{named}\n"
        "there is no baseline to defend and no drop for a test to detect. "
        "The next step is the service or the contract, not the test: re-measure "
        "once the criterion passes at all."
    )


def _cutoff(claim: SizingClaim, samples: int) -> int:
    return fisher_cutoff(claim.baseline_successes, claim.baseline_trials, samples, claim.alpha)


def _power(claim: SizingClaim, samples: int) -> float:
    return resolved_power(
        claim.baseline_successes,
        claim.baseline_trials,
        samples,
        claim.alpha,
        claim.design_alternative_rate,
    )


def _explanation(
    claim: SizingClaim, samples: int, *, governing: bool, several: bool, only_catch: bool = False
) -> str:
    """The plain-language explanation sentence, at the actual run size."""
    cutoff = _cutoff(claim, samples)
    power = _power(claim, samples)
    prefix = f"criterion {claim.criterion}: " if several else ""
    suffix = " (this criterion set the run size)" if governing and several else ""
    verb = "only catch" if only_catch else "catch"
    return (
        f"{prefix}Against your baseline of {claim.baseline_successes} of "
        f"{claim.baseline_trials}, this test passes when at least {cutoff} of its "
        f"{samples} samples succeed; an unchanged service is flagged at most "
        f"{_percent(1 - claim.confidence)} of the time. This design will {verb} a genuine "
        f"drop to {_percent(claim.design_alternative_rate)} about {_percent(power)} of the "
        f"time (its resolved power); a smaller drop is still flagged, less often.{suffix}"
    )


def _sizing_table(claims: list[SizingClaim], samples: int, governing: str) -> list[str]:
    """The multi-criterion sizing block as one aligned table: a row per
    claim, priced at the governing run size, the governing row marked."""
    headers = (
        "criterion",
        "catch a drop to",
        "confidence",
        "drop caught",
        "passes at",
        "needs alone",
    )
    rows = []
    for claim in claims:
        rows.append(
            (
                claim.criterion,
                _percent(claim.design_alternative_rate),
                _percent(claim.confidence),
                f"about {_percent(_power(claim, samples))}",
                f"{_cutoff(claim, samples)} of {samples}",
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
        criteria.append(
            {
                "criterion": claim.criterion,
                "baseline_successes": claim.baseline_successes,
                "baseline_trials": claim.baseline_trials,
                "design_alternative_rate": claim.design_alternative_rate,
                "confidence": claim.confidence,
                "required_n": claim.required_n,
                "cutoff": _cutoff(claim, samples),
                "resolved_power": _power(claim, samples),
            }
        )
    lead = next((c for c in claims if c.criterion == governing), claims[0])
    lead_row = next(row for row in criteria if row["criterion"] == lead.criterion)
    return {
        "approach": "confidence-first (risk-driven)",
        "decisionRule": "regression/fisher",
        "criteria": criteria,
        "governing": {"criterion": governing, "samples": samples},
        "baseline": lead.baseline_rate,
        "confidence": lead.confidence,
        "designAlternativeRate": lead.design_alternative_rate,
        "targetPower": lead.target_power,
        "requiredSamples": lead.required_n,
        "cutoff": lead_row["cutoff"],
        "resolvedPower": lead_row["resolved_power"],
        "resolvedDetectableRate": resolved_detectable_rate(
            lead.baseline_successes, lead.baseline_trials, samples, lead.alpha, lead.target_power
        ),
        "explanation": "\n".join(explanations),
    }
