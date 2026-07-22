"""The runner: load, instantiate, execute, render, persist.

This package is a thin facade over the per-verb submodules — ``run``
(test/measure, `_run`), ``explore`` (`_explore`), ``optimize`` (`_optimize`
plus the per-entry loop in `_optimize_loop`), ``check`` (`_check`), and
``report`` (`_report`) — over the shared artefact-directory layout and
progress line (`_shared`).
"""

from ._check import check
from ._explore import AbortedConfiguration, ConfigurationExploration, ExplorationRun, explore
from ._optimize import optimize
from ._optimize_loop import OptimizationOutcome
from ._report import report
from ._run import run
from ._shared import (
    DEFAULT_BASELINE_DIR,
    DEFAULT_EXPLORATIONS_DIR,
    DEFAULT_OPTIMIZATIONS_DIR,
    DEFAULT_VERDICT_DIR,
    MAVAI_EXPLORE_POINTER,
)
from ._shared import _tty_progress as _tty_progress

__all__ = [
    "DEFAULT_BASELINE_DIR",
    "DEFAULT_EXPLORATIONS_DIR",
    "DEFAULT_OPTIMIZATIONS_DIR",
    "DEFAULT_VERDICT_DIR",
    "MAVAI_EXPLORE_POINTER",
    "AbortedConfiguration",
    "ConfigurationExploration",
    "ExplorationRun",
    "OptimizationOutcome",
    "check",
    "explore",
    "optimize",
    "report",
    "run",
]
