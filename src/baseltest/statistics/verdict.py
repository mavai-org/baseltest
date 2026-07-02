"""Verdict evaluation: deciding pass or fail for a single test criterion.

The statistical rigour lives in *how the threshold was constructed*
(see `threshold.py`), not in a separate hypothesis test performed here.
Evaluation is a direct comparison of the observed result against that
threshold, in one of two postures:

- **Compliance posture** (`evaluate_compliance`) -- pass iff the observed
  rate clears the derived threshold. The threshold already embeds the
  confidence via the Wilson construction, so "is 87% above 85%?" is not a
  naive comparison once the 85% is itself a confidence-aware bound.
- **Regression posture** (`evaluate_regression`) -- pass iff the observed
  count meets or exceeds an integer lower-tail cutoff. The cutoff is the
  binding decision artefact; the observed rate is informational only.

A z-statistic and one-sided p-value are computed alongside the compliance
verdict, but they are diagnostics, not the decision rule -- they're
reported for downstream tooling (multi-run aggregation, transparency
reporting) and never change whether the criterion passed.

`INCONCLUSIVE` deliberately does not appear as a value either function can
return: it is not a property of a single criterion's arithmetic, but arises
upstream (an unmet feasibility gate, zero trials) and is a caller-level
concern. `Verdict` includes it only as a state a caller may attach after
combining a criterion's outcome with that upstream context, for example
when summarizing multiple runs.
"""

import math
from dataclasses import dataclass
from enum import Enum
from statistics import NormalDist

_NORMAL = NormalDist()


class Verdict(Enum):
    """The outcome of a single test criterion."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def _validate_counts(successes: int, trials: int) -> None:
    if trials <= 0:
        raise ValueError("trials must be a positive integer")
    if successes < 0:
        raise ValueError("successes must be non-negative")
    if successes > trials:
        raise ValueError("successes cannot exceed trials")


@dataclass(frozen=True, slots=True)
class ComplianceVerdict:
    """The result of evaluating an observed rate against a Wilson-derived threshold."""

    verdict: Verdict
    observed_rate: float
    threshold: float
    z_statistic: float
    p_value: float
    confidence_level: float
    false_positive_probability: float

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS


def evaluate_compliance(
    successes: int,
    trials: int,
    threshold: float,
    confidence_level: float = 0.95,
) -> ComplianceVerdict:
    """Evaluate an observed rate against a threshold (compliance posture).

    Args:
        successes: Observed number of passes (`k`). Must satisfy
            `0 <= successes <= trials`.
        trials: Total number of samples (`n`). Must be positive.
        threshold: The derived threshold to clear, in `[0, 1]`.
        confidence_level: The confidence underwriting the threshold,
            strictly between 0 and 1. Used only to report
            `false_positive_probability`; it does not affect the
            pass/fail decision itself.

    Returns:
        The verdict plus its diagnostics. The z-statistic and p-value
        are undefined (returned as `0.0` / `0.5`) when `threshold` is
        0 or 1, since the underlying variance is zero in that case --
        every non-negative rate trivially clears (or every rate below
        1 trivially fails) a 0/1 threshold, so the diagnostic adds no
        information there.

    Raises:
        ValueError: If `trials <= 0`, `successes` is out of range, or
            `confidence_level` is not strictly between 0 and 1.
    """
    _validate_counts(successes, trials)
    if math.isnan(threshold) or not (0.0 <= threshold <= 1.0):
        raise ValueError("threshold must be between 0 and 1")
    if math.isnan(confidence_level) or not (0.0 < confidence_level < 1.0):
        raise ValueError("confidence_level must be strictly between 0 and 1")

    observed_rate = successes / trials
    passed = observed_rate >= threshold

    variance = threshold * (1 - threshold)
    if variance > 0:
        z_statistic = (observed_rate - threshold) / math.sqrt(variance / trials)
    else:
        z_statistic = 0.0
    p_value = _NORMAL.cdf(z_statistic)

    return ComplianceVerdict(
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        observed_rate=observed_rate,
        threshold=threshold,
        z_statistic=z_statistic,
        p_value=p_value,
        confidence_level=confidence_level,
        false_positive_probability=1 - confidence_level,
    )


@dataclass(frozen=True, slots=True)
class RegressionVerdict:
    """The result of evaluating an observed count against an integer cutoff."""

    verdict: Verdict
    successes: int
    trials: int
    cutoff: int

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS

    @property
    def observed_rate(self) -> float:
        """The observed rate, reported for context -- not the decision basis."""
        return self.successes / self.trials


def evaluate_regression(successes: int, trials: int, cutoff: int) -> RegressionVerdict:
    """Evaluate an observed count against an integer lower-tail cutoff.

    Args:
        successes: Observed number of passes (`k`). Must satisfy
            `0 <= successes <= trials`.
        trials: Total number of samples (`n`). Must be positive.
        cutoff: The minimum number of successes required to pass, in
            `[0, trials]`.

    Returns:
        The verdict. The observed rate is available for context but is
        not what determined the outcome.

    Raises:
        ValueError: If `trials <= 0`, `successes` is out of range, or
            `cutoff` is outside `[0, trials]`.
    """
    _validate_counts(successes, trials)
    if cutoff < 0 or cutoff > trials:
        raise ValueError("cutoff must be between 0 and trials")

    passed = successes >= cutoff
    return RegressionVerdict(
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        successes=successes,
        trials=trials,
        cutoff=cutoff,
    )
