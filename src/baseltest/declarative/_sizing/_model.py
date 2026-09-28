"""The sizing value model: the resolved claim, the run result, and the error.

Pure data — no I/O, no statistics beyond the rate a count states. ``SizingClaim`` is one empirical
criterion's resolved claim and pricing; ``ResolvedSizing`` is the whole
``test``-verb outcome; ``_EmpiricalCriterion`` is the intermediate the
resolver folds evidence and claims into.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from baseltest.contract import BaseltestError
from baseltest.statistics import alpha_from_confidence

# An unclaimed explicit-samples design is called weak when the rate it can
# reliably catch sits more than this far below the baseline rate.
_WEAK_DESIGN_MARGIN = 0.05

# A computed requirement above this is still honoured — the operator asked
# for it — but the output notes the honest cost and suggests relaxing.
LARGE_RUN_NOTE_LIMIT = 1000


class SizingRefusalError(BaseltestError):
    """A run refused (or declined) before any service invocation; exit 2."""


@dataclass(frozen=True, slots=True)
class SizingClaim:
    """One empirical criterion's resolved sizing claim and its pricing.

    ``design_alternative_rate`` is the true rate at which the test is to
    reach ``target_power`` — declared (``declared``), or, for an unclaimed
    explicit-samples run, the rate the chosen size can reliably catch.
    ``required_n`` is the resolved-sizing answer against the observed
    baseline (``None`` when not computed).
    """

    criterion: str
    baseline_successes: int
    baseline_trials: int
    design_alternative_rate: float
    confidence: float
    target_power: float
    required_n: int | None
    declared: bool = True

    @property
    def baseline_rate(self) -> float:
        """The baseline's observed rate ``K_b / n_b``."""
        return self.baseline_successes / self.baseline_trials

    @property
    def alpha(self) -> float:
        """The one-sided level ``1 - confidence``."""
        return alpha_from_confidence(self.confidence)


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
    design_alternative_rates: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "design_alternative_rates", MappingProxyType(dict(self.design_alternative_rates))
        )


@dataclass(frozen=True, slots=True)
class _EmpiricalCriterion:
    """One sizeable empirical criterion: its evidence and resolved claim."""

    name: str
    baseline_successes: int
    baseline_trials: int
    confidence: float
    design_alternative_rate: float | None

    @property
    def baseline_rate(self) -> float:
        """The baseline's observed rate ``K_b / n_b``."""
        return self.baseline_successes / self.baseline_trials

    @property
    def alpha(self) -> float:
        """The one-sided level ``1 - confidence``."""
        return alpha_from_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class _UnsizeableCriterion:
    """An empirical criterion whose baseline no sample size can price.

    A baseline that passed nothing has a rate of zero, and sizing is defined
    only for a design alternative rate strictly below it
    (``ZERO_BASELINE``) — so there is no drop to detect at any size. Carried out of the
    selection rather than dropped from it: a run sized over the criteria
    that happened to be priceable would present a verdict over the contract
    while covering part of it.
    """

    name: str
    trials: int
