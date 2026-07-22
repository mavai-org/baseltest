"""Pricing a claim: required N, the governing run size, the over-reach warning.

The per-criterion sample requirement (``required_samples_for_power``), the
governing run size across claims (the largest requirement, floored by the
normative feasibility minimum), and the plain-language push-back when a
tolerance sits at or above the proven baseline.
"""

from baseltest.statistics import required_samples_for_power

from ._model import SizingClaim, _EmpiricalCriterion
from ._rates import _percent


def _priced_claim(criterion: _EmpiricalCriterion, target_power: float) -> SizingClaim:
    assert criterion.tolerated_rate is not None
    return SizingClaim(
        criterion=criterion.name,
        baseline_rate=criterion.baseline_rate,
        baseline_trials=criterion.baseline_trials,
        tolerated_rate=criterion.tolerated_rate,
        confidence=criterion.confidence,
        target_power=target_power,
        required_n=required_samples_for_power(
            criterion.baseline_rate,
            criterion.tolerated_rate,
            criterion.confidence,
            target_power,
        ),
    )


def _governing_samples(claims: list[SizingClaim], normative_minimum: int) -> tuple[int, str]:
    """The run size: the largest per-criterion requirement, floored by the
    normative criteria's feasibility minimum."""
    governing_claim = max(claims, key=lambda c: c.required_n or 0)
    samples = governing_claim.required_n or 0
    if normative_minimum > samples:
        return normative_minimum, governing_claim.criterion
    return samples, governing_claim.criterion


def _over_reach_message(criterion: _EmpiricalCriterion) -> str:
    baseline = _percent(criterion.baseline_rate)
    asked = _percent(criterion.tolerated_rate or 0.0)
    suggestion = max(1, round(criterion.baseline_rate * 100) - 3)
    return (
        "Hold on — this asks for more than the evidence supports.\n"
        f"\n"
        f"Your measure run of {criterion.baseline_trials} samples proved criterion "
        f"{criterion.name} at {baseline}. That is the most reliable estimate you have "
        f"of how it truly performs. You have asked the test to confirm the real pass "
        f"rate is at least {asked} — at or above that measurement.\n"
        "\n"
        "Unless the system has genuinely improved since that run, this test is very "
        "likely to fail: it must prove the system is better than your own best "
        "measurement showed. Running more samples will not rescue it — a larger sample "
        f"pins the result more tightly around the true ~{baseline}, making a pass even "
        "less likely. Only a small, lucky sample could clear the bar.\n"
        "\n"
        "What you can do:\n"
        f"  - Set your lowest acceptable rate below {baseline} — the level you are "
        f'willing to defend as "still good enough" (e.g. --tolerate {suggestion})\n'
        "  - If you truly believe the system has improved, re-measure the baseline "
        "first (basel measure), then set your tolerance against the new proven rate."
    )
