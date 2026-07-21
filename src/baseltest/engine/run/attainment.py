"""Bar attainment: was a criterion's bar met, missed, or out of reach?

The post-run companion to feasibility (see ``feasibility._preflight``). Where
preflight refuses an infeasible verification test up front, this classifies a
completed criterion's outcome — met, genuinely missed, or *unsupportable*
because even a perfect run of this size could not have cleared the bar. That
last case is a feasibility fact about the experiment, not the service: it is
computed here (a Wilson counterfactual on a hypothetical perfect run), then
read by the renderers.
"""

from enum import StrEnum

from baseltest.statistics.verdict import Verdict
from baseltest.statistics.wilson import wilson_lower_bound

from .model import CriterionResult


class BarAttainment(StrEnum):
    """How a completed criterion stands against its declared bar.

    ``UNSUPPORTABLE`` marks a bar that even a perfect run of this size could
    not have cleared — the family's three-way experiment-time judgement,
    distinct from a bar that was reachable but simply not met.
    """

    MET = "met"
    NOT_MET = "not met"
    UNSUPPORTABLE = "unsupportable"


def bar_attainment(result: CriterionResult) -> BarAttainment:
    """Classify a completed criterion's outcome against its declared bar."""
    criterion = result.criterion
    if criterion.threshold is None:
        raise ValueError(f"criterion {criterion.name!r} declares no bar")
    if result.verdict is Verdict.PASS:
        return BarAttainment.MET
    trials = result.tally.trials
    if criterion.cutoff is not None:
        # Regression posture: a perfect run supports the bar iff the run is
        # at least as long as the cutoff demands.
        return BarAttainment.UNSUPPORTABLE if criterion.cutoff > trials else BarAttainment.NOT_MET
    best_possible = wilson_lower_bound(trials, trials, criterion.confidence)
    if best_possible < criterion.threshold:
        return BarAttainment.UNSUPPORTABLE
    return BarAttainment.NOT_MET
