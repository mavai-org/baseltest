"""Risk-driven sample sizing against a moving acceptance floor.

A baseline-derived test does not judge against a fixed bar: its acceptance
floor is the one-sided Wilson lower bound of the baseline rate computed at
the test's *own* sample size, so the floor falls as the sample shrinks -- a
small sample proves less, so less is demanded of it. The closed-form power
pair in `power` holds the threshold constant and therefore overstates the
power of small designs; the functions here put the moving floor inside the
calculation.

The caller declares a **minimum acceptable rate** -- the worst true pass
rate they are willing to tolerate; a declared bound, not a measured
estimate. `power_at` prices the probability that a service truly at that
rate fails a test of a given size; `required_samples_for_power` finds the
smallest size meeting a target power; `detectable_rate` inverts the
question for a fixed, affordable size.

The floor and the power calculation share one z convention: the floor is
computed by `wilson.wilson_lower_bound_from_rate`, the same one-sided
construction used for threshold derivation throughout this package.

The construction is defined for a minimum acceptable rate strictly below
the baseline rate only. At or above it, the floor sits below the tolerated
rate at every sample size, power falls as the sample grows, and no size
achieves a useful target power -- such a design asks the test to detect a
"degradation" the baseline already exceeds. Callers should re-measure the
baseline rather than asserting improvement through the tolerance.
"""

import math

from scipy.stats import norm

from .wilson import wilson_lower_bound_from_rate

# A requirement beyond this is a misconfigured tolerance, not a plan.
_REQUIRED_SAMPLES_CAP = 10_000_000

# Bisection resolution for the detectable-rate inversion.
_DETECTABLE_RATE_TOLERANCE = 1e-10


def _validate_unit_interval(name: str, value: float) -> None:
    if math.isnan(value) or not (0.0 < value < 1.0):
        raise ValueError(f"{name} must be strictly between 0 and 1")


def _validate_sizing_domain(baseline_rate: float, minimum_acceptable_rate: float) -> None:
    _validate_unit_interval("baseline_rate", baseline_rate)
    _validate_unit_interval("minimum_acceptable_rate", minimum_acceptable_rate)
    if minimum_acceptable_rate >= baseline_rate:
        raise ValueError(
            f"minimum_acceptable_rate ({minimum_acceptable_rate}) must sit strictly "
            f"below baseline_rate ({baseline_rate}): the tolerance declares how far "
            "below the measured baseline a true rate may drop; to demand more than "
            "the baseline delivered, re-measure the baseline rather than raising "
            "the tolerance"
        )


def power_at(
    sample_size: int,
    baseline_rate: float,
    minimum_acceptable_rate: float,
    confidence_level: float = 0.95,
) -> float:
    """Compute the self-consistent power of a test of `sample_size` samples.

    The acceptance floor is the one-sided Wilson lower bound of
    `baseline_rate` at `sample_size` itself -- the bar this test would
    actually apply. The result is the probability that a service whose
    true rate is `minimum_acceptable_rate` fails the test, i.e. that a
    degradation at least that severe is detected.

    Args:
        sample_size: The candidate test sample size. Must be positive.
        baseline_rate: The measured baseline pass rate, strictly between
            0 and 1 (a perfect baseline should be reduced to its effective
            rate before sizing).
        minimum_acceptable_rate: The declared worst tolerable true rate,
            strictly between 0 and `baseline_rate`.
        confidence_level: The confidence the acceptance floor is derived
            at, strictly between 0 and 1.

    Returns:
        The power, in `[0, 1]`.

    Raises:
        ValueError: If `sample_size` is not positive, any rate is out of
            range, or `minimum_acceptable_rate` does not sit strictly
            below `baseline_rate`.
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    _validate_sizing_domain(baseline_rate, minimum_acceptable_rate)
    _validate_unit_interval("confidence_level", confidence_level)

    floor = wilson_lower_bound_from_rate(baseline_rate, sample_size, confidence_level)
    standard_error = math.sqrt(
        minimum_acceptable_rate * (1 - minimum_acceptable_rate) / sample_size
    )
    return float(norm.cdf((floor - minimum_acceptable_rate) / standard_error))


def required_samples_for_power(
    baseline_rate: float,
    minimum_acceptable_rate: float,
    confidence_level: float = 0.95,
    target_power: float = 0.8,
) -> int:
    """Compute the smallest sample size whose self-consistent power meets
    `target_power`.

    Within the domain, growing the sample both raises the acceptance floor
    toward the baseline rate and shrinks the standard error, so the power
    is increasing in the sample size and the minimum is well defined. It is
    found by doubling until the target is met, then bisecting.

    Args:
        baseline_rate: The measured baseline pass rate, strictly between
            0 and 1.
        minimum_acceptable_rate: The declared worst tolerable true rate,
            strictly between 0 and `baseline_rate`.
        confidence_level: The confidence the acceptance floor is derived
            at, strictly between 0 and 1.
        target_power: The desired detection probability, strictly between
            0 and 1.

    Returns:
        The smallest sample size meeting the target power.

    Raises:
        ValueError: If any input is out of range, or if the requirement
            exceeds 10,000,000 samples -- a tolerance that tight against
            that baseline is a misconfiguration, not a plan.
    """
    _validate_sizing_domain(baseline_rate, minimum_acceptable_rate)
    _validate_unit_interval("confidence_level", confidence_level)
    _validate_unit_interval("target_power", target_power)

    def power_of(n: int) -> float:
        return power_at(n, baseline_rate, minimum_acceptable_rate, confidence_level)

    upper = 1
    while power_of(upper) < target_power:
        upper *= 2
        if upper > _REQUIRED_SAMPLES_CAP:
            raise ValueError(
                f"required sample size exceeds {_REQUIRED_SAMPLES_CAP}: "
                f"minimum_acceptable_rate ({minimum_acceptable_rate}) is too close "
                f"to baseline_rate ({baseline_rate}) to detect at power "
                f"{target_power}"
            )
    if upper == 1:
        return 1

    # Invariant: power(lower) < target_power <= power(upper).
    lower = upper // 2
    while lower + 1 < upper:
        mid = (lower + upper) // 2
        if power_of(mid) >= target_power:
            upper = mid
        else:
            lower = mid
    return upper


def detectable_rate(
    sample_size: int,
    baseline_rate: float,
    confidence_level: float = 0.95,
    target_power: float = 0.8,
) -> float:
    """Compute the largest tolerable true rate detectable at `target_power`
    with `sample_size` samples.

    The inversion of `required_samples_for_power` for a fixed, affordable
    sample size: the highest minimum acceptable rate (the smallest drop
    from the baseline) at which the self-consistent power still meets the
    target. Found by bisection over `(0, baseline_rate)` to an absolute
    tolerance of 1e-10.

    Args:
        sample_size: The fixed test sample size. Must be positive.
        baseline_rate: The measured baseline pass rate, strictly between
            0 and 1.
        confidence_level: The confidence the acceptance floor is derived
            at, strictly between 0 and 1.
        target_power: The desired detection probability, strictly between
            0 and 1.

    Returns:
        The detectable rate, strictly between 0 and `baseline_rate`.

    Raises:
        ValueError: If `sample_size` is not positive or any other input is
            out of range.
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    _validate_unit_interval("baseline_rate", baseline_rate)
    _validate_unit_interval("confidence_level", confidence_level)
    _validate_unit_interval("target_power", target_power)

    lower = 1e-9
    upper = baseline_rate - 1e-9
    while upper - lower > _DETECTABLE_RATE_TOLERANCE:
        mid = (lower + upper) / 2
        if power_at(sample_size, baseline_rate, mid, confidence_level) >= target_power:
            lower = mid
        else:
            upper = mid
    return lower
