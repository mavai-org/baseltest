"""Power analysis and sample size calculation for a binomial proportion test.

Given a baseline pass rate, the minimum degradation worth detecting
(the effect size), and a desired confidence and power, `required_sample_size`
answers "how many samples do I need to run?". Its inverse, `achieved_power`,
answers "given the samples I'm actually planning to run, how good is my
detection capability?".

Both use the normal approximation to the binomial proportion test, comparing
the baseline rate `p0` against the degraded alternative `p1 = p0 - effect_size`
-- this is a one-sided test for a *decrease* in pass rate, matching the
"has this gotten worse" question a probabilistic regression test asks.
"""

import math

from scipy.stats import norm

from ._validation import validate_unit_interval


def _validate_rates(baseline_rate: float, effect_size: float) -> float:
    if not (0.0 < baseline_rate <= 1.0) or math.isnan(baseline_rate):
        raise ValueError("baseline_rate must be greater than 0 and at most 1")
    if not (0.0 < effect_size < 1.0) or math.isnan(effect_size):
        raise ValueError("effect_size must be strictly between 0 and 1")
    alternative_rate = baseline_rate - effect_size
    if alternative_rate <= 0.0:
        raise ValueError("effect_size cannot exceed baseline_rate")
    return alternative_rate


def required_sample_size(
    confidence_level: float,
    effect_size: float,
    power: float,
    baseline_rate: float,
) -> int:
    """Compute the minimum sample size to detect a degradation at a given power.

    Args:
        confidence_level: Desired confidence (`1 - alpha`), strictly
            between 0 and 1.
        effect_size: Minimum detectable decrease in pass rate, strictly
            between 0 and 1.
        power: Desired power (`1 - beta`), strictly between 0 and 1.
        baseline_rate: The baseline (null hypothesis) pass rate, in
            `(0, 1]`.

    Returns:
        The required sample size, rounded up to the next integer so
        that the achieved power is at least the declared power.

    Raises:
        ValueError: If any input is out of range, or if `effect_size`
            is at least as large as `baseline_rate` (the alternative
            rate would be non-positive).
    """
    validate_unit_interval("confidence_level", confidence_level)
    validate_unit_interval("power", power)
    alternative_rate = _validate_rates(baseline_rate, effect_size)

    z_alpha = float(norm.ppf(confidence_level))
    z_beta = float(norm.ppf(power))
    sigma0 = math.sqrt(baseline_rate * (1 - baseline_rate))
    sigma1 = math.sqrt(alternative_rate * (1 - alternative_rate))

    n = ((z_alpha * sigma0 + z_beta * sigma1) / effect_size) ** 2
    return math.ceil(n)


def achieved_power(
    sample_size: int,
    confidence_level: float,
    effect_size: float,
    baseline_rate: float,
) -> float:
    """Compute the statistical power achieved by a given sample size.

    The inverse of `required_sample_size`: rearranges the same normal
    approximation to solve for power instead of sample size.

    Args:
        sample_size: The planned (or actual) sample size. Must be
            positive.
        confidence_level: Desired confidence (`1 - alpha`), strictly
            between 0 and 1.
        effect_size: Minimum detectable decrease in pass rate, strictly
            between 0 and 1.
        baseline_rate: The baseline (null hypothesis) pass rate, in
            `(0, 1]`.

    Returns:
        The achieved power, in `[0, 1]`.

    Raises:
        ValueError: If any input is out of range, `sample_size` is not
            positive, or `effect_size` is at least as large as
            `baseline_rate`.
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    validate_unit_interval("confidence_level", confidence_level)
    alternative_rate = _validate_rates(baseline_rate, effect_size)

    z_alpha = float(norm.ppf(confidence_level))
    sigma0 = math.sqrt(baseline_rate * (1 - baseline_rate))
    sigma1 = math.sqrt(alternative_rate * (1 - alternative_rate))

    z_beta = (effect_size * math.sqrt(sample_size) - z_alpha * sigma0) / sigma1
    return float(norm.cdf(z_beta))
