"""The three sizing modes: explicit-samples, risk-driven, and over-reach.

Each takes the resolved empirical criteria and the interaction channel,
prices the design, discloses it, guards the weak or over-reaching cases,
and returns the ``ResolvedSizing``. The resolver dispatches to exactly one.
"""

import json

from baseltest.statistics import resolved_detectable_rate

from .._parser import ContractDeclaration
from ._criteria import _normative_minimum
from ._model import (
    _WEAK_DESIGN_MARGIN,
    LARGE_RUN_NOTE_LIMIT,
    ResolvedSizing,
    SizingClaim,
    SizingRefusalError,
    _EmpiricalCriterion,
)
from ._pricing import _governing_samples, _over_reach_message, _priced_claim
from ._prompts import _Interaction
from ._rates import _percent
from ._render import _explanation, _json_payload, _sizing_table


def _explicit_samples_mode(
    criteria: list[_EmpiricalCriterion],
    samples: int,
    target_power: float,
    interaction: _Interaction,
) -> ResolvedSizing:
    """Explicit-samples mode: run at the typed size, but price it first and
    require confirmation for a weak design.

    A size larger than the baseline is not priced: the engine refuses it
    before any sample runs (``TEST_LARGER_THAN_BASELINE``), with every other
    configuration error beside it.
    """
    if any(samples > criterion.baseline_trials for criterion in criteria):
        return ResolvedSizing(samples=samples, provenance="explicit", approach="sample-size-first")
    several = len(criteria) > 1
    claims: list[SizingClaim] = []
    weak_lines: list[str] = []
    interaction.say(f"\nYou asked to run {samples} samples.\n\nWhat this means:")
    for criterion in criteria:
        if criterion.design_alternative_rate is not None:
            claim = _priced_claim(criterion, target_power)
            required = claim.required_n or 0
            weak = samples < required
            interaction.say(
                _explanation(claim, samples, governing=False, several=several, only_catch=weak)
            )
            if weak:
                weak_lines.append(
                    f"To reliably catch a drop to {_percent(claim.design_alternative_rate)} "
                    f"on criterion {claim.criterion}, you would need about {required} samples."
                )
        else:
            catchable = resolved_detectable_rate(
                criterion.baseline_successes,
                criterion.baseline_trials,
                samples,
                criterion.alpha,
                target_power,
            )
            if catchable is None:
                weak_lines.append(
                    f"At {samples} samples no drop on criterion {criterion.name} is caught "
                    f"{_percent(target_power)} of the time — not even a collapse to 0%."
                )
                continue
            claim = SizingClaim(
                criterion=criterion.name,
                baseline_successes=criterion.baseline_successes,
                baseline_trials=criterion.baseline_trials,
                design_alternative_rate=catchable,
                confidence=criterion.confidence,
                target_power=target_power,
                required_n=None,
                declared=False,
            )
            weak = catchable < criterion.baseline_rate - _WEAK_DESIGN_MARGIN
            interaction.say(
                _explanation(claim, samples, governing=False, several=several, only_catch=weak)
            )
            if weak:
                weak_lines.append(
                    f"A system that has quietly degraded to around "
                    f"{_percent(catchable)} on criterion {criterion.name} would still "
                    f"pass most of the time — that is far below your baseline of "
                    f"{_percent(criterion.baseline_rate)}."
                )
        claims.append(claim)
    if weak_lines and not (interaction.accept_weak_design or interaction.force):
        interaction.say("\nwarning: this is a weak test.")
        for line in weak_lines:
            interaction.say(f"  {line}")
        if not interaction.interactive:
            raise SizingRefusalError(
                "a weak test design needs an explicit go-ahead: re-run with "
                "--accept-weak-design to confirm it, raise --samples, or declare "
                "what the test must catch with --tolerate"
            )
        if not interaction.confirm("Continue anyway?", default_yes=False):
            raise SizingRefusalError("run declined — no samples were taken")
    if interaction.emit_json and claims:
        interaction.say(json.dumps(_json_payload(claims, samples, None, []), indent=2))
    return ResolvedSizing(
        samples=samples,
        provenance="explicit",
        claims=tuple(claims),
        governing=None,
        approach="sample-size-first",
        design_alternative_rates=_declared_rates(claims),
    )


def _risk_driven_mode(
    criteria: list[_EmpiricalCriterion],
    declaration: ContractDeclaration,
    target_power: float,
    interaction: _Interaction,
    *,
    prompted: bool,
) -> ResolvedSizing:
    """Fully-specified (or just-prompted) risk-driven sizing: compute the
    governing size, explain it, and — after prompting — confirm it."""
    claims = [_priced_claim(criterion, target_power) for criterion in criteria]
    samples, governing = _governing_samples(claims, _normative_minimum(declaration))
    several = len(claims) > 1
    explanations = [
        _explanation(claim, samples, governing=claim.criterion == governing, several=several)
        for claim in claims
    ]
    if interaction.emit_json:
        interaction.say(
            json.dumps(_json_payload(claims, samples, governing, explanations), indent=2)
        )
    else:
        qualifier = "rates to catch" if several else "rate to catch"
        interaction.say(
            f"\nThis test needs {samples} samples (computed from your declared {qualifier})."
        )
        if several:
            interaction.say("")
            for line in _sizing_table(claims, samples, governing):
                interaction.say(line)
            interaction.say("")
        else:
            interaction.say(explanations[0])
            interaction.say("")
        if samples > LARGE_RUN_NOTE_LIMIT:
            interaction.say(
                f"\nnote: a run of {samples} samples is the honest cost of the confidence "
                "and the rate to catch you asked for. To spend less, declare a lower rate "
                "to catch (--tolerate) or accept a lower confidence (--confidence)."
            )
    if (
        prompted
        and not interaction.accept_weak_design
        and not interaction.confirm(f"\nRun {samples} samples now?", default_yes=True)
    ):
        raise SizingRefusalError("run declined — no samples were taken")
    return ResolvedSizing(
        samples=samples,
        provenance="risk-driven",
        claims=tuple(claims),
        governing=governing,
        approach="confidence-first (risk-driven)",
        design_alternative_rates=_declared_rates(claims),
    )


def _declared_rates(claims: list[SizingClaim]) -> dict[str, float]:
    """The declared design alternative rates, by criterion, for the run's report."""
    return {claim.criterion: claim.design_alternative_rate for claim in claims if claim.declared}


def _over_reach_mode(
    criteria: list[_EmpiricalCriterion],
    offender: _EmpiricalCriterion,
    samples: int | None,
    target_power: float,
    interaction: _Interaction,
) -> ResolvedSizing:
    """A design alternative rate at or above the baseline rate
    (``ALTERNATIVE_NOT_BELOW_BASELINE``): warn, never search for a required
    size, and demand a deliberate override (interactive confirmation, or
    ``--force`` in automation)."""
    interaction.say("\n" + _over_reach_message(offender))
    if not interaction.force:
        if not interaction.interactive:
            raise SizingRefusalError(
                f"ALTERNATIVE_NOT_BELOW_BASELINE: the rate to catch for criterion "
                f"{offender.name} is at or above its baseline rate — re-run with --force "
                "to design the test anyway"
            )
        if not interaction.confirm("\nDesign the test anyway?", default_yes=False):
            raise SizingRefusalError("run declined — no samples were taken")
    if samples is None:
        raise SizingRefusalError(
            "no number of samples can be computed for a rate to catch at or above the "
            "baseline rate (there is no drop to catch) — choose the size yourself with "
            "--samples N"
        )
    # The over-reaching claim prices nothing; explain what the chosen size
    # actually buys instead, per criterion.
    priced = [
        c
        if c.design_alternative_rate is None or c.design_alternative_rate < c.baseline_rate
        else _EmpiricalCriterion(
            name=c.name,
            baseline_successes=c.baseline_successes,
            baseline_trials=c.baseline_trials,
            confidence=c.confidence,
            design_alternative_rate=None,
        )
        for c in criteria
    ]
    return _explicit_samples_mode(priced, samples, target_power, interaction)
