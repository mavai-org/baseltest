"""The sizing value model: the resolved claim, the run result, and the error.

Pure data — no I/O, no statistics. ``SizingClaim`` is one empirical
criterion's resolved claim and pricing; ``ResolvedSizing`` is the whole
``test``-verb outcome; ``_EmpiricalCriterion`` is the intermediate the
resolver folds evidence and claims into.
"""

from dataclasses import dataclass

from baseltest.contract import BaseltestError

# An unclaimed explicit-samples design is called weak when the drop it can
# actually catch sits more than this far below the proven baseline.
_WEAK_DESIGN_MARGIN = 0.05

# A computed requirement above this is still honoured — the operator asked
# for it — but the output notes the honest cost and suggests relaxing.
LARGE_RUN_NOTE_LIMIT = 1000


class SizingRefusalError(BaseltestError):
    """A run refused (or declined) before any service invocation; exit 2."""


@dataclass(frozen=True, slots=True)
class SizingClaim:
    """One empirical criterion's resolved sizing claim and its pricing."""

    criterion: str
    baseline_rate: float
    baseline_trials: int
    tolerated_rate: float
    confidence: float
    target_power: float
    required_n: int | None


@dataclass(frozen=True, slots=True)
class ResolvedSizing:
    """The ``test`` verb's resolved run size and everything it disclosed.

    ``samples`` is ``None`` on the legacy path (no empirical sizing
    engaged): the runner's own sizing story applies unchanged.
    """

    samples: int | None
    provenance: str | None = None
    claims: tuple[SizingClaim, ...] = ()
    governing: str | None = None
    approach: str | None = None


@dataclass(frozen=True, slots=True)
class _EmpiricalCriterion:
    """One sizeable empirical criterion: its evidence and resolved claim."""

    name: str
    baseline_rate: float
    baseline_trials: int
    confidence: float
    tolerated_rate: float | None
