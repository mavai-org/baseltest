"""Judgement: a criterion's tally becomes a lower bound and a verdict."""

from baseltest.contract import Criterion, CriterionTally
from baseltest.statistics.verdict import Verdict, evaluate_regression
from baseltest.statistics.wilson import wilson_lower_bound


def _judge(criterion: Criterion, tally: CriterionTally) -> tuple[float | None, Verdict | None]:
    """A thresholded criterion's bound and verdict; (None, None) otherwise.

    Two postures, per the criterion's decision artefact. A baseline-derived
    criterion carries an integer cutoff and passes iff the raw observed
    success count meets it — the confidence correction already lives in the
    derivation, so no second bound is stacked on the test side. A declared
    threshold is judged in the compliance posture: the test sample's own
    Wilson lower bound must clear it. The bound is reported in both
    postures; in the regression posture it is context, not the rule.
    """
    if criterion.threshold is None or tally.trials == 0:
        return None, None
    bound = wilson_lower_bound(tally.successes, tally.trials, criterion.confidence)
    if criterion.cutoff is not None:
        if criterion.cutoff > tally.trials:
            # A run too short for its cutoff cannot meet the bar; that is a
            # failed bar, not a defect.
            return bound, Verdict.FAIL
        return bound, evaluate_regression(tally.successes, tally.trials, criterion.cutoff).verdict
    verdict = Verdict.PASS if bound >= criterion.threshold else Verdict.FAIL
    return bound, verdict
