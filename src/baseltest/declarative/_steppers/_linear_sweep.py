"""The ``linear-sweep`` built-in stepper: walk one numeric key in fixed steps.

A fixed grid you want fully characterised is an exploration; what makes the
sweep an optimisation is the sequential machinery — the scorer, best-tracking,
and above all plateau stopping that abandons the walk as soon as it stops
paying.
"""

from typing import Any

from .._errors import ContractConfigurationError
from ._context import OptimizeContext
from ._contract import StepFunction
from ._numeric import _NUMERIC_TOLERANCE, _numeric


def _linear_sweep(key: str, step: float, stop: float) -> StepFunction:
    """Walk ``key`` from its starting value in fixed increments up to ``stop``.

    A fixed grid you want fully characterised is an exploration; what
    makes the sweep an optimisation is the sequential machinery — the
    scorer, best-tracking, and above all plateau stopping that abandons
    the walk as soon as it stops paying.
    """
    if step == 0:
        raise ContractConfigurationError(
            "stepper 'linear-sweep': `step:` must be non-zero — a zero step "
            "re-measures the same configuration forever"
        )

    def advance(current: dict[str, Any], ctx: OptimizeContext) -> dict[str, Any] | None:
        value = _numeric(current[key], "linear-sweep", key)
        proposed = value + step
        past_stop = (
            proposed > stop + _NUMERIC_TOLERANCE
            if step > 0
            else (proposed < stop - _NUMERIC_TOLERANCE)
        )
        if past_stop:
            return None
        return {**current, key: round(proposed, 12)}

    return advance
