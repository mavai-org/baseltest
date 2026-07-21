"""Bar standing: how a declared bar stands after a run.

A reader-facing interpretation of a result — met, not met, or unsupportable
by a run of this size — distinct from the pass/fail verdict itself. It is a
presentation concern currently housed in the engine.
"""

from enum import StrEnum

from baseltest.statistics.verdict import Verdict
from baseltest.statistics.wilson import wilson_lower_bound

from .model import CriterionResult


class BarStanding(StrEnum):
    """A declared bar's experiment-time standing.

    ``UNSUPPORTABLE`` marks a bar that even a perfect run of this size could
    not have supported — the family's three-way experiment-time judgement,
    distinct from a bar that was simply not met.
    """

    MET = "met"
    NOT_MET = "not met"
    UNSUPPORTABLE = "unsupportable"


def bar_standing(result: CriterionResult) -> BarStanding:
    """The recorded standing of a declared bar."""
    criterion = result.criterion
    if criterion.threshold is None:
        raise ValueError(f"criterion {criterion.name!r} declares no bar")
    if result.verdict is Verdict.PASS:
        return BarStanding.MET
    trials = result.tally.trials
    if criterion.cutoff is not None:
        # Regression posture: a perfect run supports the bar iff the run is
        # at least as long as the cutoff demands.
        return BarStanding.UNSUPPORTABLE if criterion.cutoff > trials else BarStanding.NOT_MET
    best_possible = wilson_lower_bound(trials, trials, criterion.confidence)
    if best_possible < criterion.threshold:
        return BarStanding.UNSUPPORTABLE
    return BarStanding.NOT_MET
