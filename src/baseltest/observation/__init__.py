"""The run observation: the shared descriptive record of one configuration's run.

A descriptive experiment observes a configuration by sampling it: the counts,
per-criterion rates, failure distribution, cost, gated latency, and per-sample
projection of one run — never a bound, threshold, or verdict. Both descriptive
experiments produce these (an explore run one per grid configuration, an
optimize run one per iteration), so the record and its emitter live here, below
both, and neither experiment depends on the other.
"""

from .emit import observation_lines
from .record import CriterionStatistics, FailureEntry, RunObservation

__all__ = [
    "CriterionStatistics",
    "FailureEntry",
    "RunObservation",
    "observation_lines",
]
