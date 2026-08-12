"""The withheld-criteria canary: did the tuner improve what it could see?

A stepper that withholds criteria from its tuner declares which ones. This
module states what happened to the two groups over the run — the criteria
the tuner could see, and the criteria it could not.

Optimising against a proxy eventually finds the gaps between what the
proxy detects and what it meant, and the reading on the way there is a
rising score. Withholding a control group is what makes that visible: if
the seen criteria climb while the unseen ones do not, the prompt is being
fitted to the measure rather than to the requirement.

**Stated, never judged.** This is triage in the standings' sense — pooled
counts and observed fractions, no interval, no threshold, no verdict.
Whether a given divergence is large enough to condemn a run is a
statistical claim, and one this framework does not yet own; a reader who
can see both movements can decide, and a framework that invented a
cutoff here would be inventing exactly the kind of number the family
requires its oracle to publish first.
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from .._steppers import IterationResult

WITHHELD_KEY = "withheldCriteria"


def canary_reading(
    history: Sequence[IterationResult], best_index: int, withheld: frozenset[str]
) -> str | None:
    """How the seen and unseen criteria moved from the baseline to the best.

    ``None`` when there is nothing to say: no criteria were withheld, the
    run has no baseline to move from, or the withheld names matched no
    criterion the run measured.
    """
    if not withheld or not history:
        return None
    baseline, best = history[0], history[best_index]
    measured = {evidence.name for evidence in baseline.evidence}
    matched = withheld & measured
    if not matched:
        # The author asked for a control group and did not get one. Saying
        # so is more useful than silence: a mistyped name would otherwise
        # withhold nothing and read as a clean run.
        return (
            f"withheld criteria {', '.join(sorted(withheld))} matched none of the "
            f"criteria this run measured ({', '.join(sorted(measured))}) — "
            "the tuner saw everything"
        )
    seen = measured - matched
    if not seen:
        return (
            f"every criterion was withheld ({', '.join(sorted(matched))}) — "
            "the tuner had no evidence to work from"
        )
    return (
        f"seen criteria {_movement(baseline, best, seen)}; "
        f"withheld criteria {_movement(baseline, best, matched)}"
    )


def _movement(baseline: IterationResult, best: IterationResult, names: AbstractSet[str]) -> str:
    """One group's pooled pass rate at the baseline and at the best iteration."""
    start, end = _rate(baseline, names), _rate(best, names)
    if start is None or end is None:
        return "not measured"
    return f"{start:.2f} → {end:.2f} ({end - start:+.2f})"


def _rate(result: IterationResult, names: AbstractSet[str]) -> float | None:
    """The group's pooled pass rate: trials summed across its criteria.

    A sum of counts, not a mean of rates — criteria differ in how many
    trials they saw, and averaging their rates would weight a criterion
    that ran twice equally with one that ran two hundred times.
    """
    passed = sum(e.passed for e in result.evidence if e.name in names)
    trials = sum(e.trials for e in result.evidence if e.name in names)
    return passed / trials if trials else None


def withheld_names(provenance: object) -> frozenset[str]:
    """The criteria a stepper declared it withheld, read from its provenance.

    A stepper that withholds says so; the loop reports on what was
    declared. Any stepper adopting the same declaration gets the same
    reporting without the loop knowing anything about the algorithm.
    """
    if not isinstance(provenance, str):
        return frozenset()
    return frozenset(name.strip() for name in provenance.split(",") if name.strip())
