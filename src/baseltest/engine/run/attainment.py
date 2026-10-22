"""Bar attainment: was a criterion's bar met, missed, or out of reach?

The post-run companion to feasibility (see ``feasibility._preflight``). Where
preflight refuses an infeasible verification test up front, this classifies a
completed criterion's outcome — met, genuinely missed, or *unsupportable*
because even a perfect run of this size could not have cleared the bar. That
last case is a feasibility fact about the experiment, not the service: under
``compliance/exact-binomial`` no count of this size can pass (``k_min`` does
not exist), and it is read here off the criterion's decision.

A requirement's attainment is always read under ``compliance/exact-binomial``,
whatever rule decided the run: a run under smoke intent is decided by
``compliance/smoke-exact-binomial``, whose PASS states only that no
shortfall was found, but whether the bar was *met* — and whether it could
have been — remains a fact about the experiment, not a smoke verdict.
"""

from enum import StrEnum

from baseltest.statistics import RegressionVerdict, Verdict

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
    decision = result.decision
    if decision is None:
        raise ValueError(f"criterion {result.criterion.name!r} declares no bar")
    if isinstance(decision, RegressionVerdict):
        return BarAttainment.MET if decision.verdict is Verdict.PASS else BarAttainment.NOT_MET
    k_min = decision.minimum_passing
    if k_min is None:
        return BarAttainment.UNSUPPORTABLE
    return BarAttainment.MET if decision.successes >= k_min else BarAttainment.NOT_MET
