"""Empirical regression under ``regression/fisher`` (Statistical Companion §3.4).

A test is judged against the baseline it was derived from by the one-sided
Fisher exact test, expressed as an integer cutoff on the test's success
count. For each test count ``k_t`` the p-value is the hypergeometric lower
tail ``P(X <= k_t)``, ``X`` the number of the ``s = K_b + k_t`` pooled
successes that fall in the test's ``n_t`` of the ``n_b + n_t`` trials; a
count fails when its p-value is at most alpha, and the cutoff ``c`` is the
smallest count whose p-value exceeds it. The test passes iff ``K_t >= c``.

The cutoff is monotone in the baseline count — a perfect baseline needs no
special case — and the rule never exceeds alpha in the experiment where the
baseline and the test are both random. Everything here is an exact finite
sum; nothing is approximated or simulated.

Alongside the cutoff this module computes what a report discloses about it:
the size at the assumed common rate, the design power (baseline and test
both yet to be drawn), the resolved power (the baseline observed, its
cutoff fixed), the minimum detectable degradation, and the threshold-first
inversion (the implied alpha of a declared cutoff, §6.3).
"""

from dataclasses import dataclass

import numpy as np
from scipy.stats import binom, hypergeom

from ._arrays import BoolArray, IntArray
from ._exact import at_most_alpha_each, fisher_p_value_exact

# The baseline counts carrying all but a negligible share of the binomial
# mass: the design power sums over them only (the truncation moves the power
# by less than 2e-17).
_WINDOW_MASS = 1e-17

# A declared cutoff whose implied alpha exceeds this is unsound (§6.3).
_SOUND_IMPLIED_ALPHA = 0.20

MDD_POWER = 0.80
"""The power at which the minimum detectable degradation is stated (§5.6)."""


def fisher_p_value(
    test_successes: int, baseline_successes: int, baseline_trials: int, test_samples: int
) -> float:
    """The one-sided Fisher p-value ``P(X <= k_t)`` of a test count."""
    pooled = baseline_successes + test_successes
    return float(
        hypergeom.cdf(test_successes, baseline_trials + test_samples, pooled, test_samples)
    )


def _fails(
    test_successes: IntArray,
    baseline_successes: IntArray,
    baseline_trials: int,
    test_samples: int,
    alpha: float,
) -> BoolArray:
    """Whether each test count fails: its p-value is at most alpha (inclusive,
    under the exact-boundary convention)."""
    p_values = np.asarray(
        hypergeom.cdf(
            test_successes,
            baseline_trials + test_samples,
            baseline_successes + test_successes,
            test_samples,
        ),
        dtype=np.float64,
    )
    return at_most_alpha_each(
        p_values,
        alpha,
        lambda i: fisher_p_value_exact(
            int(test_successes[i]), int(baseline_successes[i]), baseline_trials, test_samples
        ),
    )


def fisher_cutoffs(
    baseline_successes: IntArray, baseline_trials: int, test_samples: int, alpha: float
) -> IntArray:
    """The cutoff of ``regression/fisher`` for each of several baseline counts.

    The p-value is non-decreasing in the test count, so each cutoff is found
    by bisection between a virtual failing count ``-1`` and ``n_t`` (whose
    p-value is 1).
    """
    k_b = np.asarray(baseline_successes, dtype=np.int64)
    low = np.full(k_b.shape, -1, dtype=np.int64)
    high = np.full(k_b.shape, test_samples, dtype=np.int64)
    while True:
        open_ = np.flatnonzero(high - low > 1)
        if open_.size == 0:
            return high
        mid = (low[open_] + high[open_]) // 2
        failing = _fails(mid, k_b[open_], baseline_trials, test_samples, alpha)
        high[open_[~failing]] = mid[~failing]
        low[open_[failing]] = mid[failing]


def _cutoffs_near(
    baseline_successes: IntArray,
    baseline_trials: int,
    test_samples: int,
    alpha: float,
    guess: IntArray,
) -> IntArray:
    """The same cutoffs as :func:`fisher_cutoffs`, walked from a close guess.

    A sizing search evaluates the cutoffs at one test size after another;
    starting from the previous size's cutoffs makes each a step or two of
    walking rather than a full bisection. The answer is the definition's —
    the smallest count whose p-value exceeds alpha — whatever the guess.
    """
    k_b = np.asarray(baseline_successes, dtype=np.int64)
    cut = np.clip(guess, 0, test_samples).astype(np.int64)
    while True:  # raise any cutoff whose count still fails
        index = np.flatnonzero(_fails(cut, k_b, baseline_trials, test_samples, alpha))
        if index.size == 0:
            break
        cut[index] += 1
    while True:  # lower any cutoff whose predecessor passes too
        candidates = np.flatnonzero(cut > 0)
        passing = ~_fails(
            cut[candidates] - 1, k_b[candidates], baseline_trials, test_samples, alpha
        )
        index = candidates[passing]
        if index.size == 0:
            return cut
        cut[index] -= 1


def fisher_cutoff(
    baseline_successes: int, baseline_trials: int, test_samples: int, alpha: float
) -> int:
    """The integer cutoff ``c`` of ``regression/fisher``: PASS iff ``K_t >= c``.

    Args:
        baseline_successes: ``K_b``, in ``0..n_b``.
        baseline_trials: ``n_b``, positive.
        test_samples: ``n_t``, positive.
        alpha: The one-sided level, in ``(0, 1)``.

    Raises:
        ValueError: On counts or a level out of range.
    """
    _validate(baseline_successes, baseline_trials, test_samples, alpha)
    return int(
        fisher_cutoffs(np.array([baseline_successes]), baseline_trials, test_samples, alpha)[0]
    )


def _validate(
    baseline_successes: int, baseline_trials: int, test_samples: int, alpha: float
) -> None:
    if baseline_trials <= 0:
        raise ValueError("baseline_trials must be a positive integer")
    if test_samples <= 0:
        raise ValueError("test_samples must be a positive integer")
    if not 0 <= baseline_successes <= baseline_trials:
        raise ValueError("baseline_successes must be in 0..baseline_trials")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")


def baseline_window(baseline_trials: int, rate: float) -> IntArray:
    """The baseline counts carrying all but ``2e-17`` of ``Bin(n_b, rate)``."""
    if rate >= 1.0:
        return np.array([baseline_trials], dtype=np.int64)
    if rate <= 0.0:
        return np.array([0], dtype=np.int64)
    low = int(binom.ppf(_WINDOW_MASS, baseline_trials, rate))
    high = baseline_trials - int(binom.ppf(_WINDOW_MASS, baseline_trials, 1.0 - rate))
    return np.arange(low, high + 1, dtype=np.int64)


def _fail_probability(
    cutoffs: IntArray,
    baseline_counts: IntArray,
    baseline_trials: int,
    baseline_rate: float,
    test_samples: int,
    test_rate: float,
) -> float:
    """``sum_k P_{p_b}(K_b = k) P_{p_t}(K_t < c(k))`` over the given counts."""
    weights = binom.pmf(baseline_counts, baseline_trials, baseline_rate)
    below = binom.cdf(cutoffs - 1, test_samples, test_rate)
    return float(np.sum(weights * below))


@dataclass(frozen=True, slots=True)
class RegressionDerivation:
    """The cutoff of ``regression/fisher`` for one configuration, and its report.

    Attributes:
        cutoff: The binding decision artefact: PASS iff ``K_t >= cutoff``.
        test_samples: ``n_t``, the size the cutoff was derived for.
        alpha: The one-sided level.
        size_at_assumed_common_rate: The exact unconditional
            false-degradation-signal probability were the unknown common
            rate equal to the baseline's observed rate — a property of the
            procedure at that rate, not of the run; ``None`` when the
            baseline rate is 0 or 1, where it is degenerate.
    """

    cutoff: int
    test_samples: int
    alpha: float
    size_at_assumed_common_rate: float | None

    @property
    def threshold_real(self) -> float:
        """The cutoff as a rate, ``c / n_t`` — the displayed threshold."""
        return self.cutoff / self.test_samples

    @property
    def displayed_rate(self) -> float:
        """``c / n_t`` rounded to six places, as a report displays it."""
        return round(self.cutoff / self.test_samples, 6)


def derive_regression_cutoff(
    baseline_successes: int, baseline_trials: int, test_samples: int, alpha: float
) -> RegressionDerivation:
    """Derive the cutoff of ``regression/fisher`` and its informational size.

    The design rule that a test may not exceed its baseline is judged by
    the caller before any derivation (see ``rules.check_test_size``).

    Raises:
        ValueError: On counts or a level out of range.
    """
    cutoff = fisher_cutoff(baseline_successes, baseline_trials, test_samples, alpha)
    return RegressionDerivation(
        cutoff=cutoff,
        test_samples=test_samples,
        alpha=alpha,
        size_at_assumed_common_rate=size_at_assumed_common_rate(
            baseline_successes, baseline_trials, test_samples, alpha
        ),
    )


def size_at_assumed_common_rate(
    baseline_successes: int, baseline_trials: int, test_samples: int, alpha: float
) -> float | None:
    """The procedure's false-degradation-signal probability at ``p = K_b / n_b``.

    ``None`` at a baseline rate of 0 or 1, where it is degenerate.
    """
    rate = baseline_successes / baseline_trials
    if rate in (0.0, 1.0):
        return None
    return design_power(baseline_trials, test_samples, alpha, rate, rate)


def design_power(
    baseline_trials: int,
    test_samples: int,
    alpha: float,
    baseline_rate: float,
    design_alternative_rate: float,
) -> float:
    """The exact power of ``regression/fisher`` with the baseline yet to be drawn.

    ``sum_k P_{p0}(K_b = k) P_{p_design}(K_t < c(k))``: the probability that
    a service truly at the design alternative rate fails the test, averaged
    over the baseline counts a baseline of ``n_b`` at ``p0`` could return.
    At ``p_design = p0`` it is the size at that common rate.
    """
    counts = baseline_window(baseline_trials, baseline_rate)
    cutoffs = fisher_cutoffs(counts, baseline_trials, test_samples, alpha)
    return _fail_probability(
        cutoffs, counts, baseline_trials, baseline_rate, test_samples, design_alternative_rate
    )


def resolved_power(
    baseline_successes: int,
    baseline_trials: int,
    test_samples: int,
    alpha: float,
    design_alternative_rate: float,
) -> float:
    """The power of the test resolved against an observed baseline.

    The observed ``K_b`` fixes the cutoff, so the power at the design
    alternative rate is ``P_{p_design}(K_t < c(K_b))``. It answers a
    different question from :func:`design_power` and is reported beside
    it, named apart.
    """
    cutoff = fisher_cutoff(baseline_successes, baseline_trials, test_samples, alpha)
    return float(binom.cdf(cutoff - 1, test_samples, design_alternative_rate))


def minimum_detectable_degradation(
    baseline_trials: int,
    test_samples: int,
    alpha: float,
    baseline_rate: float,
    power: float = MDD_POWER,
) -> float | None:
    """The smallest drop the design detects with ``power``: inverts the design power.

    The smallest ``delta`` at which the design power against
    ``p_b - delta`` reaches ``power``, by bisection to ``1e-12``; ``None``
    when even a test rate of 0 falls short — no degradation is detectable
    at that power.
    """
    counts = baseline_window(baseline_trials, baseline_rate)
    cutoffs = fisher_cutoffs(counts, baseline_trials, test_samples, alpha)

    def power_at(delta: float) -> float:
        return _fail_probability(
            cutoffs, counts, baseline_trials, baseline_rate, test_samples, baseline_rate - delta
        )

    if power_at(baseline_rate) < power:
        return None
    low, high = 0.0, baseline_rate
    while high - low > 1e-12:
        mid = (low + high) / 2
        if power_at(mid) >= power:
            high = mid
        else:
            low = mid
    return high


def resolved_detectable_rate(
    baseline_successes: int,
    baseline_trials: int,
    test_samples: int,
    alpha: float,
    power: float = MDD_POWER,
) -> float | None:
    """The largest true rate the resolved test detects with ``power``.

    Inverts the resolved power, the cutoff fixed by the observed baseline:
    the largest ``p`` with ``P_p(K_t < c) >= power``, by bisection to
    ``1e-10``; ``None`` when not even a rate of 0 reaches it (a cutoff of 0
    fails nothing).
    """
    cutoff = fisher_cutoff(baseline_successes, baseline_trials, test_samples, alpha)

    def power_at(rate: float) -> float:
        return float(binom.cdf(cutoff - 1, test_samples, rate))

    if power_at(0.0) < power:
        return None
    low, high = 0.0, 1.0
    while high - low > 1e-10:
        mid = (low + high) / 2
        if power_at(mid) >= power:
            low = mid
        else:
            high = mid
    return low


@dataclass(frozen=True, slots=True)
class ImpliedAlpha:
    """The threshold-first inversion of a declared cutoff (§6.3).

    Attributes:
        alpha: The smallest alpha at which ``regression/fisher`` yields the
            cutoff (0 for a cutoff of 0, the infimum); ``None`` when no
            alpha yields it — the rule skips that cutoff.
        is_sound: Whether the implied alpha is at most 0.20; ``None`` when
            there is no implied alpha.
    """

    alpha: float | None
    is_sound: bool | None


def implied_alpha(
    baseline_successes: int, baseline_trials: int, test_samples: int, cutoff: int
) -> ImpliedAlpha:
    """The implied alpha of a declared cutoff under ``regression/fisher``.

    The rule gives ``c`` exactly when ``P(X <= c - 1) <= alpha < P(X <= c)``,
    so the implied alpha is the p-value at ``c - 1``.

    Raises:
        ValueError: On a cutoff outside ``0..n_t``.
    """
    if not 0 <= cutoff <= test_samples:
        raise ValueError("cutoff must be between 0 and test_samples")
    if cutoff == 0:
        return ImpliedAlpha(alpha=0.0, is_sound=True)
    below = fisher_p_value(cutoff - 1, baseline_successes, baseline_trials, test_samples)
    at = fisher_p_value(cutoff, baseline_successes, baseline_trials, test_samples)
    if not below < at:
        return ImpliedAlpha(alpha=None, is_sound=None)
    return ImpliedAlpha(alpha=below, is_sound=below <= _SOUND_IMPLIED_ALPHA)
