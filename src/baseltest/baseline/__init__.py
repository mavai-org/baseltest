"""The baseline artefact: the durable record of a measurement run.

A measurement persists what was observed -- per-criterion counts and rates,
identity, and provenance -- as a YAML artefact other tooling can later read.
This package owns the artefact's schema and is its **single writer**: the
serialisation lives here and nowhere else. The writer accepts
characterisation data as input, so any caller that has measured something
-- this framework's own measure runs, or an external characteriser -- hands
its data over rather than emitting the format itself.

Nothing in this package reads baselines back for threshold derivation; the
artefact is a durable record whose consumption is a deliberately separate,
later capability.
"""

from .record import BaselineRecord, CriterionCharacterisation, NormativeJudgement
from .writer import baseline_filename, render_baseline, write_baseline

__all__ = [
    "BaselineRecord",
    "CriterionCharacterisation",
    "NormativeJudgement",
    "baseline_filename",
    "render_baseline",
    "write_baseline",
]
