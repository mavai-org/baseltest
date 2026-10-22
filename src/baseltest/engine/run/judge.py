"""Judgement: a criterion's tally becomes a decision under its rule."""

from baseltest.contract import Criterion, CriterionTally
from baseltest.statistics import (
    MDD_POWER,
    Intent,
    design_power,
    evaluate_compliance,
    evaluate_regression,
    evaluate_smoke_compliance,
    minimum_detectable_degradation,
    resolved_power,
    wilson_lower_bound,
)

from .model import Decision, PowerDisclosure


def _judge(
    criterion: Criterion, tally: CriterionTally, intent: Intent
) -> tuple[float | None, Decision | None, PowerDisclosure | None]:
    """A judged criterion's descriptive bound, decision and power disclosure.

    A declared requirement is decided by the rule the run's intent selects:
    ``compliance/exact-binomial`` under verification, and
    ``compliance/smoke-exact-binomial`` under smoke, which FAILs only on
    evidence that the service falls short (§5.7.3). A baseline is decided by
    ``regression/fisher`` under either, its cutoff derived at this run's own
    size. The Wilson lower bound is descriptive context in both — it decides
    nothing. A criterion with no bar is characterised only: ``(None, None,
    None)``.
    """
    if not criterion.is_judged or tally.trials == 0:
        return None, None, None
    bound = wilson_lower_bound(tally.successes, tally.trials, criterion.confidence)
    if criterion.threshold is not None:
        decide = evaluate_smoke_compliance if intent is Intent.SMOKE else evaluate_compliance
        return (
            bound,
            decide(tally.successes, tally.trials, criterion.threshold, criterion.alpha),
            None,
        )
    baseline = criterion.baseline
    assert baseline is not None  # is_judged, and no threshold
    decision = evaluate_regression(
        tally.successes, tally.trials, baseline.successes, baseline.trials, criterion.alpha
    )
    return bound, decision, _power_disclosure(criterion, tally.trials)


def _power_disclosure(criterion: Criterion, test_samples: int) -> PowerDisclosure:
    """What the regression design can detect: the minimum detectable
    degradation always, and the two powers at a declared design alternative."""
    baseline = criterion.baseline
    assert baseline is not None
    rate = criterion.design_alternative_rate
    mdd = minimum_detectable_degradation(
        baseline.trials, test_samples, criterion.alpha, baseline.rate, MDD_POWER
    )
    if rate is None:
        return PowerDisclosure(minimum_detectable_degradation=mdd)
    return PowerDisclosure(
        minimum_detectable_degradation=mdd,
        design_alternative_rate=rate,
        design_power=design_power(
            baseline.trials, test_samples, criterion.alpha, baseline.rate, rate
        ),
        resolved_power=resolved_power(
            baseline.successes, baseline.trials, test_samples, criterion.alpha, rate
        ),
    )
