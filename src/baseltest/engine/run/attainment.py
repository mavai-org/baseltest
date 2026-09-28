"""Bar attainment: was a criterion's bar met, missed, or out of reach?

The post-run companion to feasibility (see ``feasibility._preflight``). Where
preflight refuses an infeasible verification test up front, this classifies a
completed criterion's outcome — met, genuinely missed, or *unsupportable*
because even a perfect run of this size could not have cleared the bar. That
last case is a feasibility fact about the experiment, not the service: under
``compliance/exact-binomial`` no count of this size can pass (``k_min`` does
not exist), and it is read here off the criterion's decision.
"""

from enum import StrEnum

from baseltest.statistics import ComplianceVerdict, Verdict

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
    if decision.verdict is Verdict.PASS:
        return BarAttainment.MET
    if isinstance(decision, ComplianceVerdict) and not decision.pass_possible:
        return BarAttainment.UNSUPPORTABLE
    return BarAttainment.NOT_MET
