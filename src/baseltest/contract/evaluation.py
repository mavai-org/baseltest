"""Per-trial evaluation: one response through one criterion, and the tallies.

Evaluation is a two-stage pipeline mirroring the authoring model: the raw
response is optionally transformed into the value under judgement, then every
postcondition must hold. Anticipated failures -- a transform that cannot
parse the response, a postcondition that does not hold -- travel as data and
count against the criterion's rate. Exceptions other than
:class:`~baseltest.contract.model.TransformError` propagate: they are
defects, and a defect aborts the run rather than being laundered into a
failed sample.
"""

from collections import Counter
from dataclasses import dataclass, field

from .model import Criterion, TransformError

_TRANSFORM_REASON_PREFIX = "transform failed"


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    """One criterion's judgement of one response.

    Attributes:
        passed: Whether the response passed the criterion.
        reason: The failure reason on a fail (the transform's failure, or the
            first postcondition that did not hold); ``None`` on a pass.
    """

    passed: bool
    reason: str | None = None


def evaluate_trial(criterion: Criterion, response: str) -> TrialEvaluation:
    """Evaluate one response against one criterion.

    Applies the criterion's transform (when declared), then every
    postcondition in declaration order; the criterion passes iff all hold.
    A :class:`TransformError` from the transform yields a failed trial with
    a transform-failure reason. Any other exception propagates as a defect.
    """
    value: object = response
    if criterion.transform is not None:
        try:
            value = criterion.transform(response)
        except TransformError as failure:
            return TrialEvaluation(passed=False, reason=f"{_TRANSFORM_REASON_PREFIX}: {failure}")
    for postcondition in criterion.postconditions:
        result = postcondition.evaluate(response, value)
        if not result.passed:
            reason = result.reason or f"postcondition {postcondition.name!r} not satisfied"
            return TrialEvaluation(passed=False, reason=reason)
    return TrialEvaluation(passed=True)


@dataclass(slots=True)
class CriterionTally:
    """Accumulated per-criterion counts over a run's samples.

    Attributes:
        successes: Trials on which the criterion passed.
        trials: Total trials evaluated.
        failure_reasons: Distribution of failure reasons over failed trials.
    """

    successes: int = 0
    trials: int = 0
    failure_reasons: Counter[str] = field(default_factory=Counter)

    def record(self, evaluation: TrialEvaluation) -> None:
        """Fold one trial's evaluation into the tally."""
        self.trials += 1
        if evaluation.passed:
            self.successes += 1
        else:
            self.failure_reasons[evaluation.reason or "unspecified"] += 1

    @property
    def observed_rate(self) -> float:
        """The observed pass rate; 0.0 before any trial is recorded."""
        if self.trials == 0:
            return 0.0
        return self.successes / self.trials
