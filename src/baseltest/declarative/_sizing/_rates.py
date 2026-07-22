"""Rate helpers shared across the sizing conversation.

Parsing a rate the operator typed (proportion or percentage), rendering a
rate as a percentage, and the perfect-baseline guard that turns a measure
run's raw success count into the rate sizing runs against.
"""

import math

from baseltest.statistics import wilson_lower_bound

from ._model import SizingRefusalError


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _parse_rate(text: str, what: str) -> float:
    """A rate as either a proportion (``0.84``) or a percentage (``84``)."""
    try:
        value = float(text)
    except ValueError:
        raise SizingRefusalError(f"{what} must be a number, got {text!r}") from None
    if value >= 1.0:
        value = value / 100
    if math.isnan(value) or not 0.0 < value < 1.0:
        raise SizingRefusalError(
            f"{what} must be a rate between 0 and 1 (or a percentage), got {text}"
        )
    return value


def _effective_rate(successes: int, trials: int, confidence: float) -> float:
    """The baseline rate sizing runs against: the perfect-baseline guard.

    A perfect measure run overstates what is known; its own one-sided
    Wilson lower bound stands in as the proven rate, exactly as the
    threshold derivation treats it.
    """
    if successes == trials:
        return wilson_lower_bound(successes, trials, confidence)
    return successes / trials
