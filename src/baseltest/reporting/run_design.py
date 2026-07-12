"""The run's design facts, as recorded and disclosed by the test report.

Plain data only: what shaped the run's size (the operational approach and,
for a risk-driven run, the declared claims), what baseline the empirical
criteria resolved, and — computed upstream, never here — what a
smaller-than-baseline run could actually detect and what it saved. The
renderers format these; the values are computed by the statistics layer
via the declarative front-end.
"""

from dataclasses import dataclass

RISK_DRIVEN_APPROACH = "confidence-first (risk-driven)"

# The canonical operational-approach glosses, in the plain register.
APPROACH_GLOSSES = {
    RISK_DRIVEN_APPROACH: (
        "the run size was computed from the declared tolerance and confidence, "
        "priced against the acceptance bar this very size derives"
    ),
    "sample-size-first": (
        "the sample size was chosen first; the acceptance bar was derived honestly at that size"
    ),
    "threshold-first": (
        "the pass bar is externally stipulated; the run judges the evidence against it"
    ),
}


@dataclass(frozen=True, slots=True)
class ClaimDisclosure:
    """One risk-driven claim as recorded: what the operator declared."""

    criterion: str
    baseline_rate: float
    tolerated_rate: float
    confidence: float
    target_power: float
    required_n: int | None


@dataclass(frozen=True, slots=True)
class BaselineDisclosure:
    """The resolved baseline's identity, for the sizing trade disclosures.

    ``baseline_rate`` is the effective rate sizing runs against (the
    measured rate, or a perfect run's own lower bound), for the weakest
    empirical criterion the run judged; ``derived_threshold`` is that
    criterion's bar at the executed size.
    """

    source_file: str
    generated_at: str
    samples: int
    baseline_rate: float
    derived_threshold: float


@dataclass(frozen=True, slots=True)
class RunDesign:
    """What shaped this run's size — recorded with the verdict, never inferred."""

    approach: str
    claims: tuple[ClaimDisclosure, ...] = ()
    governing: str | None = None
    baseline: BaselineDisclosure | None = None


@dataclass(frozen=True, slots=True)
class SizingDisclosure:
    """The computed sizing-transparency values one report row renders.

    ``detectable_rate`` is present iff the run executed fewer samples than
    the baseline's own measurement (the downsizing trade); the efficiency
    fields are its pair, estimated from the run's recorded per-sample
    average. Token savings are absent because no token metadata is
    recorded; the disclosure degrades to time-only by design.
    """

    design: RunDesign
    executed_samples: int
    target_power: float
    detectable_rate: float | None = None
    baseline_samples: int | None = None
    time_saved_fraction: float | None = None
    time_saved_ms: int | None = None
