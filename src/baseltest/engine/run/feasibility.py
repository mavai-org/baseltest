"""Feasibility: can the planned sample count support every declared bar?

Answered before any invocation. A verification test is refused when its size
cannot support a declared threshold; a measure run renders no verdict, so an
unsupportable bar is recorded rather than refused.
"""

from collections.abc import Sequence
from typing import Any

from baseltest.contract import BaseltestError, ServiceContract
from baseltest.statistics import check_feasibility

from .model import InfeasibleCriterion, Intent, RunKind, RunPlan


def derive_minimum_samples(contract: ServiceContract[Any]) -> int:
    """The smallest sample count supporting every declared threshold.

    Per-criterion, the minimum feasible sample size at that criterion's
    threshold and confidence; the governing minimum is the largest, since
    every criterion is evaluated over the same samples.

    Raises:
        ValueError: If the contract declares no thresholded criterion (an
            observation has no feasibility anchor to derive a size from).
    """
    thresholded = contract.thresholded_criteria
    if not thresholded:
        raise ValueError("cannot derive a sample count: no criterion declares a threshold")
    return max(
        check_feasibility(1, c.threshold, c.confidence).minimum_samples
        for c in thresholded
        if c.threshold is not None
    )


class InfeasibleRunError(BaseltestError):
    """The declared sample count cannot support every declared threshold.

    Raised before any invocation, under verification intent only. Carries
    the per-criterion detail so the caller can render a constructive,
    format-vocabulary refusal (never this exception's bare text).
    """

    def __init__(self, samples: int, infeasible: Sequence[InfeasibleCriterion]) -> None:
        self.samples = samples
        self.infeasible = tuple(infeasible)
        self.governing_minimum = max(c.minimum_samples for c in self.infeasible)
        names = ", ".join(c.name for c in self.infeasible)
        super().__init__(
            f"{samples} samples cannot support the declared threshold(s) of: {names}; "
            f"minimum feasible samples: {self.governing_minimum}"
        )


def _preflight(contract: ServiceContract[Any], plan: RunPlan) -> None:
    """Refuse an infeasible verification test before any invocation.

    Only a test is refused: feasibility guards verdicts, and a measure run
    renders none -- an unsupportable bar is recorded as such instead.
    """
    if plan.kind is not RunKind.TEST:
        return
    infeasible = [
        InfeasibleCriterion(
            name=c.name,
            threshold=c.threshold,
            confidence=c.confidence,
            minimum_samples=check.minimum_samples,
        )
        for c in contract.thresholded_criteria
        if c.threshold is not None
        and not (check := check_feasibility(plan.samples, c.threshold, c.confidence)).feasible
    ]
    if infeasible and plan.intent is Intent.VERIFICATION:
        raise InfeasibleRunError(plan.samples, infeasible)
