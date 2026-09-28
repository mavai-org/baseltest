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
        "the run size was computed from the declared rate to catch and confidence, "
        "priced by resolved power against the cutoff the observed baseline fixes"
    ),
    "sample-size-first": (
        "the sample size was chosen first; the cutoff was derived from the baseline at that size"
    ),
    "threshold-first": (
        "the pass bar is externally stipulated; the run judges the evidence against it"
    ),
}


@dataclass(frozen=True, slots=True)
class ClaimDisclosure:
    """One risk-driven claim as recorded: what the operator declared.

    ``design_alternative_rate`` is the true rate at which the test is to
    reach ``target_power`` (``designAlternativeRate``); ``required_n`` is the
    resolved-sizing answer against the observed baseline.
    """

    criterion: str
    baseline_rate: float
    design_alternative_rate: float
    confidence: float
    target_power: float
    required_n: int | None


@dataclass(frozen=True, slots=True)
class BaselineDisclosure:
    """The resolved baseline's identity, for the sizing trade disclosures.

    ``baseline_rate`` is the observed rate ``K_b / n_b`` of the weakest
    empirical criterion the run judged; ``derived_threshold`` is that
    criterion's cutoff as a rate, ``c / n_t``, at the executed size.
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
