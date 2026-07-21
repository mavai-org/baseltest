"""Wilson score confidence intervals for a binomial proportion.

The Wilson score interval is a confidence interval for a proportion
estimated from `k` successes out of `n` trials. Unlike the naive
(Wald) interval, it stays within `[0, 1]` and behaves sensibly at the
extremes (`k = 0` or `k = n`), which makes it the right tool for
small-sample or near-perfect pass rates -- exactly the regime
probabilistic tests operate in.

Two constructions are provided:

- `wilson_interval` -- the two-sided interval, splitting the error
  budget evenly between both tails.
- `wilson_lower_bound` / `wilson_lower_bound_from_rate` -- the
  one-sided lower bound, spending the whole error budget on the lower
  tail. This is the form used to derive conservative pass-rate
  thresholds elsewhere in this package.

The interval itself is computed by `statsmodels.stats.proportion.
proportion_confint` (`method="wilson"`), the industry-standard
implementation, rather than a hand-rolled formula. The one-sided lower
bound reuses the same two-sided routine by doubling the alpha budget
passed in, so the returned lower endpoint corresponds to spending the
full `1 - confidence_level` mass on the lower tail rather than half of
it.
"""

import math
from dataclasses import dataclass

from statsmodels.stats.proportion import proportion_confint

from ._constants import DEFAULT_CONFIDENCE_LEVEL
from ._validation import validate_confidence_level, validate_counts


@dataclass(frozen=True, slots=True)
class WilsonInterval:
    """A two-sided Wilson score confidence interval for a proportion."""

    point_estimate: float
    lower_bound: float
    upper_bound: float
    confidence_level: float

    @property
    def width(self) -> float:
        """The width of the interval (`upper_bound - lower_bound`)."""
        return self.upper_bound - self.lower_bound

    @property
    def margin_of_error(self) -> float:
        """Half the interval width."""
        return self.width / 2


def wilson_interval(
    successes: int, trials: int, confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
) -> WilsonInterval:
    """Compute the two-sided Wilson score confidence interval.

    Args:
        successes: Observed number of passes (`k`). Must satisfy
            `0 <= successes <= trials`.
        trials: Total number of samples (`n`). Must be positive.
        confidence_level: Desired confidence, strictly between 0 and 1
            (e.g. `0.95` for a 95% interval).

    Returns:
        The interval, with the point estimate and both bounds clamped
        to `[0, 1]`.

    Raises:
        ValueError: If `trials <= 0`, `successes` is out of range, or
            `confidence_level` is not strictly between 0 and 1.

    At `successes == 0` the lower bound is exactly 0 but the upper
    bound is a small positive value; at `successes == trials` the
    upper bound is exactly 1 but the lower bound is a value less than
    1. This asymmetry -- absent from the naive Wald interval -- is
    the point of using the Wilson construction for near-extreme
    pass rates.
    """
    validate_counts(successes, trials)
    validate_confidence_level(confidence_level)

    observed_rate = successes / trials
    alpha = 1 - confidence_level
    raw_lower, raw_upper = proportion_confint(successes, trials, alpha=alpha, method="wilson")

    lower_bound = max(0.0, float(raw_lower))
    upper_bound = min(1.0, float(raw_upper))
    return WilsonInterval(
        point_estimate=observed_rate,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        confidence_level=confidence_level,
    )


def wilson_lower_bound(
    successes: int, trials: int, confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
) -> float:
    """Compute the one-sided Wilson score lower bound for a proportion.

    Spends the full `1 - confidence_level` error budget on the lower
    tail (unlike `wilson_interval`, which splits it between both
    tails), producing a more conservative bound. This is the
    construction used elsewhere in this package to derive pass-rate
    thresholds from an observed baseline.

    Args:
        successes: Observed number of passes (`k`). Must satisfy
            `0 <= successes <= trials`.
        trials: Total number of samples (`n`). Must be positive.
        confidence_level: Desired confidence, strictly between 0 and 1.

    Returns:
        The lower bound, in `[0, 1]`.

    Raises:
        ValueError: If `trials <= 0`, `successes` is out of range, or
            `confidence_level` is not strictly between 0 and 1.
    """
    validate_counts(successes, trials)
    return wilson_lower_bound_from_rate(successes / trials, trials, confidence_level)


def wilson_lower_bound_from_rate(
    observed_rate: float, trials: int, confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
) -> float:
    """Compute the one-sided Wilson score lower bound from a continuous rate.

    Identical construction to `wilson_lower_bound`, but takes an
    observed rate directly rather than a `(successes, trials)` pair --
    useful when the rate being bounded was itself derived (for
    example, a baseline's own lower bound carried forward as the
    reference rate for a downstream test).

    Args:
        observed_rate: The rate to bound, in `[0, 1]`.
        trials: The sample size the bound is evaluated at. Must be
            positive.
        confidence_level: Desired confidence, strictly between 0 and 1.

    Returns:
        The lower bound, in `[0, 1]`.

    Raises:
        ValueError: If `observed_rate` is outside `[0, 1]` (or NaN),
            `trials <= 0`, or `confidence_level` is not strictly
            between 0 and 1.
    """
    if math.isnan(observed_rate) or not (0.0 <= observed_rate <= 1.0):
        raise ValueError("observed_rate must be between 0 and 1")
    if trials <= 0:
        raise ValueError("trials must be a positive integer")
    validate_confidence_level(confidence_level)

    # Spend the full alpha budget on the lower tail: `proportion_confint`
    # always splits its `alpha` in half between the two tails, so doubling
    # it here makes the *lower* endpoint the one-sided (1 - confidence_level)
    # bound. The corresponding upper endpoint is discarded.
    alpha = 1 - confidence_level
    raw_lower, _ = proportion_confint(
        observed_rate * trials, trials, alpha=2 * alpha, method="wilson"
    )
    return max(0.0, float(raw_lower))
