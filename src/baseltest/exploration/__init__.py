"""The exploration artefact: one descriptive record per explored configuration.

An explore run samples every configuration in a service's grid and writes
one YAML artefact per configuration, in the mavai family's exploration
schema (``punit-spec-1``) with human-readable, factor-derived filenames.
The artefacts are diagnostic — the developer is the only consumer, and the
core use is diffing two configurations' files side by side. They carry
descriptive statistics only: no bounds, no thresholds, no verdicts.
"""

from .record import CriterionStatistics, ExplorationRecord, LatencyBlock
from .writer import (
    exploration_stem,
    render_exploration,
    write_exploration,
)

__all__ = [
    "CriterionStatistics",
    "ExplorationRecord",
    "LatencyBlock",
    "exploration_stem",
    "render_exploration",
    "write_exploration",
]
