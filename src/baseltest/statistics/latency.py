"""Latency: empirical percentiles and the two latency decision rules (§12).

Latency is treated non-parametrically throughout the family: percentiles are
read directly off the order statistics of the *successful* latencies — those
of the samples that passed every functional criterion (§12.2.1). For a
percentile ``p`` over ``n`` sorted observations the estimate is the order
statistic at rank ``ceil(p * n)`` (nearest rank), so integer-millisecond
samples give integer-millisecond estimates.

A latency constraint is decided by the rule for its threshold source:

- an **explicit** threshold ``tau`` by ``latency/compliance-exact-binomial``
  (§12.3.4): the count of latencies at or below ``tau`` judged by the exact
  one-sided binomial test of compliance with ``p_req = p``;
- a **baseline-derived** threshold by ``latency/precedence`` (§12.4): the
  smallest baseline rank whose exact no-degradation breach probability for
  the test's nearest-rank percentile is at most alpha, the threshold being
  the observed baseline latency at that rank.

Both decisions are made after the run on the actual number of successful
latencies. Before the run the same searches on the *expected* number give
warnings and planning figures (§12.5.3), never a verdict. The raw comparison
of the observed percentile with a threshold decides nothing: it is reported
beside the decision, labelled as a raw percentile comparison. Whether a
decision binds the test is not this module's concern (§12.6): every
constraint is decided by its rule the same way, enforced or advisory.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.special import betaln, gammaln
from scipy.stats import binom

from ._exact import at_most_alpha, breach_probability_exact
from .compliance import clopper_pearson_lower, minimum_passing_count
from .rules import DecisionRule, Intent
from .verdict import Verdict

# The supported percentile levels, as integer percentages: the only levels
# the precedence rank and the non-degeneracy gate are defined for.
_SUPPORTED_PERCENT = (50, 90, 95, 99)

# The non-degeneracy minimums of §12.5.2, per supported level. The p50
# minimum of 5 is an engineering minimum (the mathematical one is 3); the
# others are the mathematical minimums.
_NON_DEGENERACY_MINIMUM = {50: 5, 90: 10, 95: 20, 99: 100}

# Tolerance on the expected-count products of §12.5.3 (a planned size times
# a passing rate), so a product that is an integer in exact arithmetic is not
# floored to the integer below it.
_EXPECTED_COUNT_SLACK = 1e-9


def _percent(percentile: float) -> int:
    """The supported level as an integer percentage, or a refusal."""
    percent = round(100 * percentile)
    if percent not in _SUPPORTED_PERCENT or abs(100 * percentile - percent) > 1e-9:
        raise ValueError(f"latency percentile must be one of p50, p90, p95, p99, got {percentile}")
    return percent


def latency_percentile(latencies: Sequence[float], percentile: float) -> float:
    """The nearest-rank empirical percentile of a latency sample.

    Args:
        latencies: Observed durations; at least one, any order.
        percentile: The percentile level, in ``(0, 1]``.

    Raises:
        ValueError: On an empty sample or a percentile outside ``(0, 1]``.
    """
    if not latencies:
        raise ValueError("cannot compute a percentile of an empty latency sample")
    if not 0 < percentile <= 1:
        raise ValueError(f"percentile must be in (0, 1], got {percentile}")
    ordered = sorted(latencies)
    rank = min(max(math.ceil(percentile * len(ordered)), 1), len(ordered))
    return ordered[rank - 1]


def latency_mean(latencies: Sequence[float]) -> float:
    """The sample mean of observed durations.

    Raises:
        ValueError: On an empty sample.
    """
    if not latencies:
        raise ValueError("cannot compute the mean of an empty latency sample")
    return sum(latencies) / len(latencies)


def latency_max(latencies: Sequence[float]) -> float:
    """The sample maximum — the ``p = 1.0`` order statistic.

    Raises:
        ValueError: On an empty sample.
    """
    if not latencies:
        raise ValueError("cannot compute the maximum of an empty latency sample")
    return max(latencies)


def minimum_contributing_samples(percentile: float) -> int:
    """The non-degeneracy minimum of a supported percentile (§12.5.2).

    Below it the empirical percentile is the sample maximum (or minimum):
    artefacts omit it, and a baseline-derived assertion cannot be decided
    on it under verification.
    """
    return _NON_DEGENERACY_MINIMUM[_percent(percentile)]


def nearest_rank(test_samples: int, percentile: float) -> int:
    """The test's nearest rank ``r = ceil(P n_t / 100)``, in integer arithmetic."""
    if test_samples <= 0:
        raise ValueError("test_samples must be a positive integer")
    return (_percent(percentile) * test_samples + 99) // 100


def breach_probability(
    baseline_trials: int, rank: int, test_samples: int, percentile: float
) -> float:
    """The no-degradation breach probability of baseline rank ``k`` (§12.4.2).

    The probability, for continuous i.i.d. latencies, that fewer than ``r``
    of the ``n_t`` test latencies fall at or below the baseline's ``k``-th
    order statistic — that the test's nearest-rank percentile exceeds it.
    """
    r = nearest_rank(test_samples, percentile)
    j = np.arange(r)
    log_terms = (
        gammaln(test_samples + 1)
        - gammaln(j + 1)
        - gammaln(test_samples - j + 1)
        + betaln(rank + j, baseline_trials - rank + 1 + test_samples - j)
        - betaln(rank, baseline_trials - rank + 1)
    )
    return float(np.sum(np.exp(log_terms)))


def _admits(
    baseline_trials: int, rank: int, test_samples: int, percentile: float, alpha: float
) -> bool:
    return at_most_alpha(
        breach_probability(baseline_trials, rank, test_samples, percentile),
        alpha,
        lambda: breach_probability_exact(
            baseline_trials, rank, test_samples, nearest_rank(test_samples, percentile)
        ),
    )


def precedence_rank(
    baseline_trials: int, test_samples: int, percentile: float, alpha: float
) -> int | None:
    """The rank of ``latency/precedence``: the smallest ``k <= n_b`` with
    ``breach(k) <= alpha``; ``None`` when none achieves it (saturated).

    The breach probability decreases in ``k``, so a rank exists exactly when
    the top rank achieves alpha, and the smallest is found by bisection.
    """
    if baseline_trials <= 0:
        raise ValueError("baseline_trials must be a positive integer")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    if not _admits(baseline_trials, baseline_trials, test_samples, percentile, alpha):
        return None
    low, high = 0, baseline_trials  # invariant: low does not admit (or is 0), high admits
    while high - low > 1:
        mid = (low + high) // 2
        if _admits(baseline_trials, mid, test_samples, percentile, alpha):
            high = mid
        else:
            low = mid
    return high


@dataclass(frozen=True, slots=True)
class PrecedenceThreshold:
    """A baseline-derived latency threshold under ``latency/precedence``.

    Attributes:
        rank: The precedence rank; ``None`` when saturated.
        threshold: The baseline latency at ``rank`` — an observed value by
            construction; ``None`` when saturated.
        saturated: No rank achieves alpha for a test of this size: the
            assertion is INCONCLUSIVE, and no rank is clamped to manufacture
            a threshold.
        breach_probability: The breach probability at ``rank``.
        test_rank: The test's nearest rank ``r``.
        n: The number of baseline latencies.
        baseline_percentile: The baseline's own nearest-rank percentile, for
            reporting; never the threshold.
    """

    rank: int | None
    threshold: float | None
    saturated: bool
    breach_probability: float | None
    test_rank: int
    n: int
    baseline_percentile: float


def derive_precedence_threshold(
    baseline_latencies: Sequence[float], test_samples: int, percentile: float, alpha: float
) -> PrecedenceThreshold:
    """The ``latency/precedence`` threshold for a test of ``test_samples``
    successful latencies against a baseline's successful latencies.

    Raises:
        ValueError: On an empty baseline, a non-positive test size, an
            unsupported percentile or a level outside ``(0, 1)``.
    """
    if not baseline_latencies:
        raise ValueError("cannot derive a latency threshold from an empty baseline")
    ordered = sorted(baseline_latencies)
    n_b = len(ordered)
    rank = precedence_rank(n_b, test_samples, percentile, alpha)
    return PrecedenceThreshold(
        rank=rank,
        threshold=None if rank is None else ordered[rank - 1],
        saturated=rank is None,
        breach_probability=(
            None if rank is None else breach_probability(n_b, rank, test_samples, percentile)
        ),
        test_rank=nearest_rank(test_samples, percentile),
        n=n_b,
        baseline_percentile=latency_percentile(ordered, percentile),
    )


def expected_successful_count(planned_samples: int, baseline_success_rate: float) -> int:
    """``floor(n_planned * p_baseline)``: an expectation, not a lower bound (§12.5.3)."""
    return math.floor(planned_samples * baseline_success_rate + _EXPECTED_COUNT_SLACK)


@dataclass(frozen=True, slots=True)
class PrecedencePlanning:
    """The pre-run existence check of a baseline-derived assertion (§12.5.3).

    Attributes:
        expected_test_samples: The expected number of successful latencies.
        warning: No rank exists at the expected count.
        planning_rank: The rank at the expected count; ``None`` under a warning.
        minimum_baseline_trials: The smallest baseline, no smaller than the
            expected count, that supports a rank for it; ``None`` when no
            successful latency is expected at all.
    """

    expected_test_samples: int
    warning: bool
    planning_rank: int | None
    minimum_baseline_trials: int | None


def plan_precedence(
    baseline_trials: int,
    planned_samples: int,
    baseline_success_rate: float,
    percentile: float,
    alpha: float,
) -> PrecedencePlanning:
    """The rank search on the expected successful count: a warning and planning
    figures, never a verdict — saturation is decided after the run."""
    expected = expected_successful_count(planned_samples, baseline_success_rate)
    if expected == 0:
        return PrecedencePlanning(0, True, None, None)
    rank = precedence_rank(baseline_trials, expected, percentile, alpha)
    minimum = expected
    while not _admits(minimum, minimum, expected, percentile, alpha):
        minimum += 1
    return PrecedencePlanning(
        expected_test_samples=expected,
        warning=rank is None,
        planning_rank=rank,
        minimum_baseline_trials=minimum,
    )


@dataclass(frozen=True, slots=True)
class NondegeneracyPlanning:
    """The pre-run non-degeneracy check (§12.5.3): a warning and a planning figure.

    Attributes:
        expected_test_samples: The expected number of successful latencies.
        minimum_contributing_samples: The percentile's minimum (§12.5.2).
        warning: The expected count falls short of the minimum.
        planned_samples_needed: The smallest planned size whose expected
            count reaches the minimum.
    """

    expected_test_samples: int
    minimum_contributing_samples: int
    warning: bool
    planned_samples_needed: int


def plan_nondegeneracy(
    percentile: float, planned_samples: int, baseline_success_rate: float
) -> NondegeneracyPlanning:
    """The expected successful count against the non-degeneracy minimum.

    Raises:
        ValueError: On a passing rate outside ``(0, 1]`` — with no passing
            baseline sample there is no rate to plan from.
    """
    if not 0.0 < baseline_success_rate <= 1.0:
        raise ValueError("baseline_success_rate must be in (0, 1]")
    minimum = minimum_contributing_samples(percentile)
    expected = expected_successful_count(planned_samples, baseline_success_rate)
    needed = math.ceil(minimum / baseline_success_rate - _EXPECTED_COUNT_SLACK)
    while expected_successful_count(needed, baseline_success_rate) < minimum:
        needed += 1
    return NondegeneracyPlanning(
        expected_test_samples=expected,
        minimum_contributing_samples=minimum,
        warning=expected < minimum,
        planned_samples_needed=needed,
    )


class ThresholdSource(StrEnum):
    """Where a latency threshold comes from (§12.3.3)."""

    EXPLICIT = "explicit"
    BASELINE_DERIVED = "baseline-derived"


class NondegeneracyOutcome(StrEnum):
    """The post-run non-degeneracy decision (§12.5.2, §12.5.4)."""

    DECIDED = "DECIDED"
    """The gate does not apply, or the percentile is not degenerate: the
    assertion is decided by its rule."""

    INCONCLUSIVE = "INCONCLUSIVE"
    """A baseline-derived assertion under verification with too few
    successful latencies."""

    INDICATIVE = "INDICATIVE"
    """A baseline-derived assertion under smoke intent with too few
    successful latencies: evaluated, and marked as a directional signal
    only."""


@dataclass(frozen=True, slots=True)
class NondegeneracyDecision:
    """Whether the gate applies, whether the percentile is degenerate, and the outcome."""

    applies: bool
    degenerate: bool
    outcome: NondegeneracyOutcome


def decide_nondegeneracy(
    percentile: float,
    test_samples: int,
    intent: Intent,
    source: ThresholdSource = ThresholdSource.BASELINE_DERIVED,
) -> NondegeneracyDecision:
    """The non-degeneracy decision on the actual count of successful latencies.

    The gate applies where the decision statistic is the empirical
    percentile — a baseline-derived assertion — and not to an explicit
    requirement, which decides on the within-threshold count and has its
    own feasibility condition. Whether the latency dimension is enforced or
    advisory does not enter (§12.6).
    """
    applies = source is ThresholdSource.BASELINE_DERIVED
    degenerate = test_samples < minimum_contributing_samples(percentile)
    if not applies or not degenerate:
        outcome = NondegeneracyOutcome.DECIDED
    elif intent is Intent.VERIFICATION:
        outcome = NondegeneracyOutcome.INCONCLUSIVE
    else:
        outcome = NondegeneracyOutcome.INDICATIVE
    return NondegeneracyDecision(applies=applies, degenerate=degenerate, outcome=outcome)


@dataclass(frozen=True, slots=True)
class LatencyCompliance:
    """An explicit latency requirement under ``latency/compliance-exact-binomial``.

    Attributes:
        test_samples: The number of successful latencies ``n_s``.
        within_threshold: ``Y``, the latencies at or below the threshold
            (a latency equal to it counts as within).
        minimum_within: ``y_min``, the smallest count demonstrating
            compliance; ``None`` when no count can pass at ``n_s``.
        verdict: PASS iff ``Y >= y_min``; INCONCLUSIVE when no count can
            pass — too few successful latencies to decide.
        false_compliance: ``P_p(Y >= y_min)``, the false-compliance
            probability at the boundary; ``None`` when no count can pass.
        clopper_pearson_lower: The one-sided lower bound on ``F(tau)``,
            reported beside the verdict; ``None`` with no latencies.
        observed_percentile_ms: The raw nearest-rank percentile, reported
            beside the decision; ``None`` with no latencies.
        raw_percentile_pass: The raw percentile comparison
            ``Q(p) <= tau``; it decides nothing.
    """

    test_samples: int
    within_threshold: int
    minimum_within: int | None
    verdict: Verdict
    false_compliance: float | None
    clopper_pearson_lower: float | None
    observed_percentile_ms: float | None
    raw_percentile_pass: bool | None

    @property
    def pass_possible(self) -> bool:
        """Whether any count of the successful latencies could pass."""
        return self.minimum_within is not None


def evaluate_latency_compliance(
    latencies: Sequence[float], threshold_ms: float, percentile: float, alpha: float
) -> LatencyCompliance:
    """Decide an explicit latency requirement on the successful latencies."""
    _percent(percentile)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    n_s = len(latencies)
    within = sum(1 for latency in latencies if latency <= threshold_ms)
    y_min = minimum_passing_count(percentile, n_s, alpha) if n_s else None
    observed = latency_percentile(latencies, percentile) if n_s else None
    if y_min is None:
        verdict = Verdict.INCONCLUSIVE
    else:
        verdict = Verdict.PASS if within >= y_min else Verdict.FAIL
    return LatencyCompliance(
        test_samples=n_s,
        within_threshold=within,
        minimum_within=y_min,
        verdict=verdict,
        false_compliance=(None if y_min is None else float(binom.sf(y_min - 1, n_s, percentile))),
        clopper_pearson_lower=clopper_pearson_lower(within, n_s, alpha) if n_s else None,
        observed_percentile_ms=observed,
        raw_percentile_pass=None if observed is None else observed <= threshold_ms,
    )


@dataclass(frozen=True, slots=True)
class LatencyJudgement:
    """One latency constraint decided by its rule on a run's successful latencies.

    Attributes:
        source: The threshold's source.
        percentile: The percentile level.
        alpha: The constraint's one-sided level.
        successful_latencies: ``n_s``, the latencies judged.
        observed_ms: The test's raw nearest-rank percentile; ``None`` with
            no latencies.
        threshold_ms: The explicit threshold, or the derived one (``None``
            when saturated or undecided).
        verdict: PASS / FAIL / INCONCLUSIVE under the constraint's rule.
        compliance: The exact-binomial decision of an explicit requirement.
        precedence: The precedence derivation of a baseline-derived
            threshold, when one was attempted.
        nondegeneracy: The non-degeneracy decision of a baseline-derived
            constraint.
    """

    source: ThresholdSource
    percentile: float
    alpha: float
    successful_latencies: int
    observed_ms: float | None
    threshold_ms: float | None
    verdict: Verdict
    compliance: LatencyCompliance | None = None
    precedence: PrecedenceThreshold | None = None
    nondegeneracy: NondegeneracyDecision | None = None

    @property
    def rule(self) -> DecisionRule:
        """The rule that decided the constraint, which its threshold source selects."""
        if self.source is ThresholdSource.EXPLICIT:
            return DecisionRule.LATENCY_COMPLIANCE_EXACT_BINOMIAL
        return DecisionRule.LATENCY_PRECEDENCE

    @property
    def indicative(self) -> bool:
        """Evaluated below the non-degeneracy minimum: a directional signal only."""
        return (
            self.nondegeneracy is not None
            and self.nondegeneracy.outcome is NondegeneracyOutcome.INDICATIVE
        )


def judge_latency_constraint(
    latencies: Sequence[float],
    percentile: float,
    alpha: float,
    *,
    source: ThresholdSource,
    intent: Intent,
    threshold_ms: float | None = None,
    baseline_latencies: Sequence[float] = (),
) -> LatencyJudgement:
    """Decide one latency constraint on the run's successful latencies.

    An explicit requirement is decided by
    ``latency/compliance-exact-binomial``; a baseline-derived constraint by
    the non-degeneracy gate and ``latency/precedence`` (a test percentile
    equal to the threshold is not a breach). The decision is the same
    whether the latency dimension is enforced or advisory (§12.6).

    Raises:
        ValueError: On an explicit constraint without a threshold, or a
            baseline-derived one without baseline latencies.
    """
    n_s = len(latencies)
    observed = latency_percentile(latencies, percentile) if n_s else None
    compliance = precedence = nondegeneracy = None
    if source is ThresholdSource.EXPLICIT:
        if threshold_ms is None:
            raise ValueError("an explicit latency constraint needs a threshold")
        tau: float | None = threshold_ms
        compliance = evaluate_latency_compliance(latencies, threshold_ms, percentile, alpha)
        verdict = compliance.verdict
    else:
        if not baseline_latencies:
            raise ValueError("a baseline-derived latency constraint needs baseline latencies")
        nondegeneracy = decide_nondegeneracy(percentile, n_s, intent, source)
        if n_s:
            precedence = derive_precedence_threshold(baseline_latencies, n_s, percentile, alpha)
        tau = None if precedence is None else precedence.threshold
        if (
            nondegeneracy.outcome is NondegeneracyOutcome.INCONCLUSIVE
            or observed is None
            or tau is None
        ):
            verdict = Verdict.INCONCLUSIVE
        else:
            verdict = Verdict.PASS if observed <= tau else Verdict.FAIL
    return LatencyJudgement(
        source=source,
        percentile=percentile,
        alpha=alpha,
        successful_latencies=n_s,
        observed_ms=observed,
        threshold_ms=tau,
        verdict=verdict,
        compliance=compliance,
        precedence=precedence,
        nondegeneracy=nondegeneracy,
    )
