"""Multi-run summary: combined false-positive risk across several criteria.

When a suite contains several independent probabilistic criteria, each with
its own false-positive probability, the suite-level risk of *at least one*
false positive is higher than any individual criterion's risk -- the
multiple-comparisons problem applied to probabilistic testing. Ten criteria
each with a 5% false-positive rate combine to roughly a 40% chance of a
spurious failure somewhere in the suite, far higher than any one of them
suggests. `summarize_runs` makes that suite-level risk explicit.

A criterion that failed carries no false-positive risk -- it never claimed
to pass -- so only passing criteria contribute to the combined probability.
An inconclusive criterion likewise made no pass claim and is excluded on
the same grounds.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .verdict import Verdict


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """The minimal shape `summarize_runs` needs from a single criterion's result."""

    verdict: Verdict
    false_positive_probability: float


@dataclass(frozen=True, slots=True)
class MultiRunSummary:
    """The combined false-positive risk across a suite of independent criteria."""

    combined_false_positive_probability: float
    total_tests: int
    passed: int
    failed: int
    inconclusive: int


def summarize_runs(outcomes: Sequence[RunOutcome]) -> MultiRunSummary:
    """Combine false-positive probabilities across independent criteria.

    Args:
        outcomes: The per-criterion outcomes to aggregate. May be
            empty.

    Returns:
        The combined false-positive probability (the probability that
        at least one passing criterion is a false positive) plus
        pass/fail/inconclusive counts. An empty sequence yields a
        combined probability of 0 -- there is nothing to be a false
        positive about.
    """
    true_negative_probability = 1.0
    passed = failed = inconclusive = 0

    for outcome in outcomes:
        if outcome.verdict is Verdict.PASS:
            passed += 1
            true_negative_probability *= 1 - outcome.false_positive_probability
        elif outcome.verdict is Verdict.FAIL:
            failed += 1
        else:
            inconclusive += 1

    return MultiRunSummary(
        combined_false_positive_probability=1 - true_negative_probability,
        total_tests=len(outcomes),
        passed=passed,
        failed=failed,
        inconclusive=inconclusive,
    )
