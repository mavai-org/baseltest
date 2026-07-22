"""The framework-shipped steppers and scorers every :class:`Registry` starts with."""

from ._context import IterationSummary
from ._contract import ScorerFunction, StepperRegistration
from ._linear_sweep import _linear_sweep
from ._prompt_engineer import _prompt_engineer
from ._refining_grid import _refining_grid


def _pass_rate(summary: IterationSummary) -> float:
    return summary.pass_rate


def builtin_scorers() -> dict[str, ScorerFunction]:
    """The framework-shipped scorers every :class:`Registry` starts with."""
    return {"pass-rate": _pass_rate}


def builtin_stepper_registrations() -> tuple[StepperRegistration, ...]:
    """The framework-shipped steppers every :class:`Registry` starts with."""
    return (
        StepperRegistration(
            name="prompt-engineer",
            factory=_prompt_engineer,
            configuration_keys=("target_key",),
            builtin=True,
        ),
        StepperRegistration(
            name="linear-sweep", factory=_linear_sweep, configuration_keys=("key",), builtin=True
        ),
        StepperRegistration(
            name="refining-grid", factory=_refining_grid, configuration_keys=("key",), builtin=True
        ),
    )
