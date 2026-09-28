"""Normative compliance under ``compliance/exact-binomial`` (§3.6, §5.5, §5.7).

A requirement ``p_req`` is demonstrated by the exact one-sided binomial test
of ``H0: p <= p_req`` against ``H1: p > p_req``. The decision artefact is the
smallest passing count ``k_min = min{k : P_{p_req}(K >= k) <= alpha}``; the
test passes iff ``K >= k_min``. A pass means the evidence supports compliance
at the configured level; a fail means compliance was not demonstrated — not
that the rate is below the requirement.

A design can pass at all only if the all-success outcome clears the test,
``p_req^n <= alpha`` — the feasibility minimum ``ceil(log alpha / log p_req)``.
Compliance tests are sized for the chance of a pass when the service is in
fact better than required, at a design alternative rate above ``p_req``.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.stats import beta, binom

from ._arrays import IntArray
from ._exact import at_most_alpha, at_most_alpha_each, binomial_upper_tail_exact

DEFAULT_SIZING_HORIZON = 20_000
"""How far the exact sizing search looks before declaring a design unsettled."""


def _validate(requirement: float, alpha: float) -> None:
    if not 0.0 < requirement < 1.0:
        raise ValueError("the requirement must be strictly between 0 and 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")


def minimum_passing_count(requirement: float, samples: int, alpha: float) -> int | None:
    """``k_min`` of ``compliance/exact-binomial``; ``None`` when no count can pass.

    Raises:
        ValueError: On a non-positive size, or a requirement or level
            outside ``(0, 1)``.
    """
    if samples <= 0:
        raise ValueError("samples must be a positive integer")
    _validate(requirement, alpha)
    counts = np.arange(samples + 1)
    upper = np.asarray(binom.sf(counts - 1, samples, requirement), dtype=np.float64)
    admitted = at_most_alpha_each(
        upper, alpha, lambda i: binomial_upper_tail_exact(i, samples, requirement)
    )
    passing = np.flatnonzero(admitted)
    return int(passing[0]) if passing.size else None


def minimum_feasible_samples(requirement: float, alpha: float) -> int:
    """The smallest size at which a pass is possible, ``ceil(log alpha / log p_req)``.

    Confirmed against the definition (``p_req^n <= alpha``, under the
    exact-boundary convention) so floating point cannot move it by one.
    """
    _validate(requirement, alpha)

    def feasible(samples: int) -> bool:
        return at_most_alpha(
            requirement**samples,
            alpha,
            lambda: binomial_upper_tail_exact(samples, samples, requirement),
        )

    samples = max(1, math.ceil(math.log(alpha) / math.log(requirement)))
    while samples > 1 and feasible(samples - 1):
        samples -= 1
    while not feasible(samples):
        samples += 1
    return samples


def clopper_pearson_lower(successes: int, samples: int, alpha: float) -> float:
    """The one-sided Clopper–Pearson lower bound at level ``1 - alpha``.

    Reported beside a compliance verdict; it decides nothing. Zero at no
    successes.
    """
    if successes == 0:
        return 0.0
    return float(beta.ppf(alpha, successes, samples - successes + 1))


def pass_probability(requirement: float, samples: int, alpha: float, rate: float) -> float:
    """``P(PASS)`` of the design at a true rate: ``P_rate(K >= k_min)``, 0 when infeasible."""
    k_min = minimum_passing_count(requirement, samples, alpha)
    if k_min is None:
        return 0.0
    return float(binom.sf(k_min - 1, samples, rate))


class AlternativeKind(StrEnum):
    """Where a compliance sizing alternative came from; the report names it."""

    MARGIN = "MARGIN"
    """``p_req + delta``: the declared assurance margin above the requirement."""

    MIDWAY = "MIDWAY"
    """``(p_req + 1) / 2``: the default where ``p_req + delta >= 1`` leaves
    the unit interval."""

    DECLARED = "DECLARED"
    """The design alternative rate the contract declared directly."""


@dataclass(frozen=True, slots=True)
class SizingAlternative:
    """The design alternative rate a compliance design is sized at, and its kind."""

    rate: float
    kind: AlternativeKind


def compliance_sizing_alternative(
    requirement: float, margin: float, declared_rate: float | None = None
) -> SizingAlternative:
    """The declared alternative, else ``p_req + delta``, else the midway rate.

    Raises:
        ValueError: On a declared rate outside ``(p_req, 1]``.
    """
    if declared_rate is not None:
        if not requirement < declared_rate <= 1.0:
            raise ValueError("a declared alternative rate must lie in (requirement, 1]")
        return SizingAlternative(rate=declared_rate, kind=AlternativeKind.DECLARED)
    if requirement + margin < 1.0:
        return SizingAlternative(rate=requirement + margin, kind=AlternativeKind.MARGIN)
    return SizingAlternative(rate=(requirement + 1.0) / 2, kind=AlternativeKind.MIDWAY)


def _minimum_passing_counts(sizes: IntArray, requirement: float, alpha: float) -> IntArray:
    """``k_min`` at every size at once (``-1`` where infeasible).

    A quantile candidate repaired against the definition until stable, so
    it equals :func:`minimum_passing_count` at every size.
    """
    k = np.asarray(binom.ppf(1 - alpha, sizes, requirement), dtype=np.int64) + 1

    def admits(counts: IntArray, index: IntArray) -> IntArray:
        upper = np.asarray(binom.sf(counts - 1, sizes[index], requirement), dtype=np.float64)
        return at_most_alpha_each(
            upper,
            alpha,
            lambda i: binomial_upper_tail_exact(int(counts[i]), int(sizes[index][i]), requirement),
        )

    everything = np.arange(sizes.size)
    while True:
        too_small = ~admits(k, everything)
        lowerable = np.flatnonzero(k > 0)
        predecessor_admitted = np.zeros(sizes.size, dtype=bool)
        predecessor_admitted[lowerable] = admits(k[lowerable] - 1, lowerable)
        if not too_small.any() and not predecessor_admitted.any():
            break
        k[too_small] += 1
        k[predecessor_admitted & ~too_small] -= 1
    return np.where(k > sizes, -1, k)


@dataclass(frozen=True, slots=True)
class ComplianceSizing:
    """Exact sizing of a compliance design (§5.5).

    Attributes:
        required_samples: The smallest ``n`` from which the power at the
            alternative stays at or above the target up to the horizon;
            ``None`` when the design has not settled by the horizon (it is
            expensive, not invalid).
        first_crossing: The smallest ``n`` whose power first reaches the
            target — reported, never the answer; ``None`` if none does.
        achieved_power: The power at ``required_samples``.
        alternative: The design alternative rate used, and its kind.
    """

    required_samples: int | None
    first_crossing: int | None
    achieved_power: float | None
    alternative: SizingAlternative


def size_compliance(
    requirement: float,
    margin: float,
    alpha: float,
    power: float,
    *,
    declared_rate: float | None = None,
    horizon: int = DEFAULT_SIZING_HORIZON,
) -> ComplianceSizing:
    """The smallest size from which ``P(PASS | alternative)`` stays at target.

    Power is a sawtooth in ``n``, and zero wherever the design is
    infeasible, so the feasibility gate sits inside the search.
    """
    _validate(requirement, alpha)
    alternative = compliance_sizing_alternative(requirement, margin, declared_rate)
    sizes = np.arange(1, horizon + 1)
    k_min = _minimum_passing_counts(sizes, requirement, alpha)
    powers = np.where(k_min < 0, 0.0, binom.sf(k_min - 1, sizes, alternative.rate))
    below = np.flatnonzero(powers < power)
    reached = np.flatnonzero(powers >= power)
    first_crossing = int(reached[0]) + 1 if reached.size else None
    if below.size and below[-1] == horizon - 1:
        return ComplianceSizing(None, first_crossing, None, alternative)
    start = int(below[-1]) + 1 if below.size else 0
    return ComplianceSizing(start + 1, first_crossing, float(powers[start]), alternative)
