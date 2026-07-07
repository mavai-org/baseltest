"""Per-trial evaluation: views, then checks, and the tallies.

Each trial resolves its checks' subjects through a :class:`TrialViews`
cache: a view is computed at most once per response — a semantic
guarantee, shared across every postcondition and criterion that names it.
Anticipated failures travel as data: a transformation that cannot process
the response fails the trial with a transform-failure reason on first use;
a postcondition that does not hold carries its own reason. Exceptions
other than :class:`~baseltest.contract.model.TransformError` propagate —
defects abort the run rather than being laundered into failed samples.
"""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .model import Criterion, TransformError

_TRANSFORM_REASON_PREFIX = "transform failed"


class TrialViews:
    """One trial's lazy, memoised view resolution.

    Constructed per response from the contract's view declarations and
    shared across all of the trial's criteria — which is what makes
    "computed at most once per response" true by construction.
    """

    def __init__(self, response: str, views: Mapping[str, Callable[[str], Any]]) -> None:
        self._response = response
        self._views = views
        self._cache: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        """The named view's value; ``raw`` is the response itself.

        Raises:
            TransformError: The view's transformation failed (anticipated;
                the caller records a failed trial).
        """
        if name == "raw":
            return self._response
        if name not in self._cache:
            self._cache[name] = self._views[name](self._response)
        return self._cache[name]


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    """One criterion's judgement of one response.

    Attributes:
        passed: Whether the response passed the criterion.
        reason: The failure reason on a fail (a view's transformation
            failure, or the first postcondition that did not hold);
            ``None`` on a pass.
    """

    passed: bool
    reason: str | None = None


def evaluate_trial(criterion: Criterion, views: TrialViews) -> TrialEvaluation:
    """Evaluate one response (via its view cache) against one criterion.

    Applies every postcondition in declaration order to its named subject;
    the criterion passes iff all hold. A :class:`TransformError` from a
    view's first computation yields a failed trial with a transform-failure
    reason. Any other exception propagates as a defect.
    """
    for postcondition in criterion.postconditions:
        try:
            subject = views.get(postcondition.view)
        except TransformError as failure:
            return TrialEvaluation(
                passed=False,
                reason=f"{_TRANSFORM_REASON_PREFIX} ({postcondition.view}): {failure}",
            )
        result = postcondition.evaluate(subject)
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
