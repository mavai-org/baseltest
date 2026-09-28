"""Verification feasibility of a normative design (§5.7.1).

Answers "can a compliance test of this size pass at all?" before any sample
is spent. Under ``compliance/exact-binomial`` a pass is possible only if the
all-success outcome clears the exact test, ``p_req^n <= alpha``, so the
minimum is ``ceil(log alpha / log p_req)``. Feasible means a pass is
possible, not that the design is adequately powered (§5.5).

Under verification intent an infeasible design is refused before it runs
(``COMPLIANCE_INFEASIBLE``); under smoke intent it runs and reports that a
pass is not possible at this size.
"""

from dataclasses import dataclass

from .compliance import minimum_feasible_samples

FEASIBILITY_CRITERION = "exact_binomial_pass_possible"
"""The name of the feasibility criterion, as reported."""


@dataclass(frozen=True, slots=True)
class FeasibilityCheck:
    """Whether a normative design of this size can pass, and the minimum that can."""

    feasible: bool
    minimum_samples: int
    sample_size: int
    target_proportion: float
    alpha: float
    criterion: str = FEASIBILITY_CRITERION


def check_feasibility(target_proportion: float, sample_size: int, alpha: float) -> FeasibilityCheck:
    """Check whether a normative design of ``sample_size`` can pass.

    Args:
        target_proportion: The requirement ``p_req``, strictly inside
            ``(0, 1)``.
        sample_size: The planned sample size, positive.
        alpha: The one-sided level, strictly inside ``(0, 1)``.

    Raises:
        ValueError: On a non-positive size, or a requirement or level
            outside ``(0, 1)``.
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    minimum = minimum_feasible_samples(target_proportion, alpha)
    return FeasibilityCheck(
        feasible=sample_size >= minimum,
        minimum_samples=minimum,
        sample_size=sample_size,
        target_proportion=target_proportion,
        alpha=alpha,
    )
