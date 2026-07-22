"""Numeric helpers shared by the numeric-factor steppers.

Coercing a configuration value to a float with a stepper-aware refusal, the
comparison tolerance, and the inclusive grid the refining-grid walks.
"""

from typing import Any

from .._errors import ContractConfigurationError

_NUMERIC_TOLERANCE = 1e-9


def _numeric(value: Any, name: str, key: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ContractConfigurationError(
            f"stepper {name!r}: configuration key {key!r} holds "
            f"{type(value).__name__} ({value!r}), not a number — this stepper "
            "walks a numeric factor"
        )
    return float(value)


def _grid_values(lo: float, hi: float, step: float) -> tuple[float, ...]:
    """The grid ``lo, lo+step, …, hi`` (both bounds included), rounded stably."""
    count = int(round((hi - lo) / step))
    values = [round(lo + index * step, 12) for index in range(count + 1)]
    if abs(values[-1] - hi) > _NUMERIC_TOLERANCE:
        values.append(round(hi, 12))
    return tuple(values)
