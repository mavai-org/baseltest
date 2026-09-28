"""The exact-boundary convention shared by every exact decision rule.

Each exact rule compares a probability with alpha by an inclusive rule: a
Fisher p-value at most alpha fails a test count, a binomial upper tail at
most alpha admits a count, a precedence breach probability at most alpha
admits a rank. At an exact boundary the probability *equals* alpha, and
double-precision evaluation can land on either side of it. The convention
(Statistical Companion §10.6):

1. compute the probability in double precision;
2. when ``|value - alpha| <= BOUNDARY_GUARD * alpha``, recompute it exactly,
   in rational arithmetic, from the declared inputs;
3. apply the inclusive rule to the exact value.

Declared rates and levels are read as the exact decimals they are written
as: 0.05 is 1/20, 0.995 is 199/200.
"""

import math
from collections.abc import Callable
from fractions import Fraction

import numpy as np

from ._arrays import BoolArray, FloatArray

BOUNDARY_GUARD = 1e-9
"""Relative band around alpha inside which a probability is recomputed exactly."""


def exact_decimal(value: float) -> Fraction:
    """A declared decimal as the exact rational it was written as.

    Fifteen significant digits recover what was typed from the nearest
    double (``0.05`` becomes ``1/20``, not the binary neighbour).
    """
    return Fraction(format(value, ".15g"))


def at_most_alpha(value: float, alpha: float, exact: Callable[[], Fraction]) -> bool:
    """Whether ``value <= alpha`` under the exact-boundary convention.

    ``exact`` computes the probability in rational arithmetic; it is called
    only inside the guard band.
    """
    if abs(value - alpha) <= BOUNDARY_GUARD * alpha:
        return exact() <= exact_decimal(alpha)
    return value <= alpha


def at_most_alpha_each(
    values: FloatArray, alpha: float, exact: Callable[[int], Fraction]
) -> BoolArray:
    """The element-wise form of :func:`at_most_alpha`.

    ``exact`` receives the index of an element inside the guard band.
    """
    out: BoolArray = values <= alpha
    near = np.flatnonzero(np.abs(values - alpha) <= BOUNDARY_GUARD * alpha)
    if near.size:
        threshold = exact_decimal(alpha)
        for index in near:
            out[index] = exact(int(index)) <= threshold
    return out


def fisher_p_value_exact(
    test_successes: int, baseline_successes: int, baseline_trials: int, test_samples: int
) -> Fraction:
    """The one-sided Fisher p-value ``P(X <= k_t)`` as a rational.

    ``X`` is hypergeometric: of ``s = k_b + k_t`` pooled successes, the
    number falling in the test's ``n_t`` of the ``n_b + n_t`` trials.
    """
    total = baseline_trials + test_samples
    pooled = baseline_successes + test_successes
    low = max(0, pooled - baseline_trials)
    if test_successes < low:
        return Fraction(0)
    numerator = sum(
        math.comb(pooled, x) * math.comb(total - pooled, test_samples - x)
        for x in range(low, test_successes + 1)
    )
    return Fraction(numerator, math.comb(total, test_samples))


def binomial_upper_tail_exact(count: int, trials: int, rate: float) -> Fraction:
    """``P(K >= count)`` for ``K ~ Bin(trials, rate)`` as a rational."""
    if count <= 0:
        return Fraction(1)
    if count > trials:
        return Fraction(0)
    q = exact_decimal(rate)
    a, b = q.numerator, q.denominator
    numerator = sum(
        math.comb(trials, j) * a**j * (b - a) ** (trials - j) for j in range(count, trials + 1)
    )
    return Fraction(numerator, b**trials)


def breach_probability_exact(
    baseline_trials: int, rank: int, test_samples: int, test_rank: int
) -> Fraction:
    """The precedence breach probability of baseline rank ``k`` as a rational.

    ``sum_{j < r} C(n_t, j) B(k + j, n_b - k + 1 + n_t - j) / B(k, n_b - k + 1)``
    with ``B(a, b) = (a - 1)! (b - 1)! / (a + b - 1)!``, collected over one
    common denominator.
    """
    n_b, k, n_t = baseline_trials, rank, test_samples
    fact = math.factorial
    numerator = fact(n_b) * sum(
        math.comb(n_t, j) * fact(k + j - 1) * fact(n_b - k + n_t - j) for j in range(test_rank)
    )
    denominator = fact(n_b + n_t) * fact(k - 1) * fact(n_b - k)
    return Fraction(numerator, denominator)
