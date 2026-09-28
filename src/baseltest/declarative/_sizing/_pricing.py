"""Pricing a claim: resolved sizing, the governing run size, the over-reach warning.

The per-criterion sample requirement is resolved sizing against the observed
baseline (``statistics.resolved_sizing``): the smallest test size from which
the power at the design alternative rate stays at or above the target, the
cutoff fixed by the baseline's count. The governing run size is the largest
requirement, floored by the normative feasibility minimum.
"""

from baseltest.statistics import resolved_sizing

from ._model import SizingClaim, SizingRefusalError, _EmpiricalCriterion
from ._rates import _percent


def _priced_claim(criterion: _EmpiricalCriterion, target_power: float) -> SizingClaim:
    """Price one declared claim by resolved sizing, or refuse ``BASELINE_TOO_SMALL``."""
    assert criterion.design_alternative_rate is not None
    sizing = resolved_sizing(
        criterion.baseline_successes,
        criterion.baseline_trials,
        criterion.design_alternative_rate,
        criterion.alpha,
        target_power,
    )
    if sizing is None:
        raise SizingRefusalError(_baseline_too_small_message(criterion, target_power))
    return SizingClaim(
        criterion=criterion.name,
        baseline_successes=criterion.baseline_successes,
        baseline_trials=criterion.baseline_trials,
        design_alternative_rate=criterion.design_alternative_rate,
        confidence=criterion.confidence,
        target_power=target_power,
        required_n=sizing.required_samples,
    )


def _baseline_too_small_message(criterion: _EmpiricalCriterion, target_power: float) -> str:
    assert criterion.design_alternative_rate is not None
    return (
        f"BASELINE_TOO_SMALL: against the baseline of {criterion.baseline_successes} of "
        f"{criterion.baseline_trials} for criterion {criterion.name}, no test of at most "
        f"{criterion.baseline_trials} samples catches a drop to "
        f"{_percent(criterion.design_alternative_rate)} with {_percent(target_power)} power "
        "and keeps doing so at every larger size the baseline admits. Measure a larger "
        "baseline (basel measure --samples N), or declare a lower rate to catch"
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
    asked = _percent(criterion.design_alternative_rate or 0.0)
    suggestion = max(1, round(criterion.baseline_rate * 100) - 3)
    return (
        "Hold on — this asks for more than the evidence supports.\n"
        f"\n"
        f"Your measure run of {criterion.baseline_trials} samples measured criterion "
        f"{criterion.name} at {baseline}. That is the most reliable estimate you have "
        f"of how it truly performs. You have asked the test to catch a drop to "
        f"{asked} — at or above that measurement, so there is no drop to catch.\n"
        "\n"
        "A regression test flags any degradation from the baseline; the rate you "
        "declare only says where it must catch one reliably, and that rate has to "
        "sit below the baseline. Running more samples will not change that.\n"
        "\n"
        "What you can do:\n"
        f"  - Declare a rate below {baseline} — the degraded rate the test must "
        f"reliably catch (e.g. --tolerate {suggestion})\n"
        "  - If you truly believe the system has improved, re-measure the baseline "
        "first (basel measure), then declare the rate against the new measurement."
    )
