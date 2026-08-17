"""Rate helpers shared across the sizing conversation.

Parsing a rate the operator typed (proportion or percentage) and rendering
a rate as a percentage. The perfect-baseline guard that turns a measure
run's success count into the rate sizing runs against lives in
`baseltest.statistics.effective_baseline_rate`, so that sizing and
threshold derivation reason from one implementation of it rather than two.
"""

import math

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
