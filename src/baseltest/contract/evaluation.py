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
from enum import StrEnum
from typing import Any

from baseltest.statistics import proportion_standard_error, proportion_variance

from .model import Criterion, DeliveryCause, TransformError

_TRANSFORM_REASON_PREFIX = "transform failed"


class Outcome(StrEnum):
    """A postcondition's three-valued status within a trial.

    ``SKIPPED`` marks a postcondition left unevaluated because a view's
    transformation failed earlier in the same trial: the views cache would
    fail every remaining check identically, so they are recorded skipped
    rather than run. (A per-input expectation that does not apply to this
    sample is not a member of the trial at all — see
    :meth:`Criterion.postconditions_for` — so it is never skipped here; it
    simply is not present.)
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TrialDefectError(Exception):
    """A defect escaping a trial's transform or postcondition evaluation.

    A transform signals an unusable response by raising
    :class:`TransformError`, an anticipated failed trial. *Any other*
    exception escaping a view's transformation or a postcondition's
    evaluation is a **defect** — a bug in the testing machinery, never a
    countable outcome and never a sample. Rather than let it propagate as a
    bare traceback, :func:`evaluate_trial` wraps it in this carrier with the
    criterion, postcondition, and view under evaluation; the sampling loop
    enriches it with the driving input's context into an actionable
    diagnosis, and the orchestration layer contains it at the configuration
    boundary. The original exception travels on ``original`` so no context
    is lost.
    """

    def __init__(
        self, *, view: str, criterion: str, postcondition: str, original: Exception
    ) -> None:
        self.view = view
        self.criterion = criterion
        self.postcondition = postcondition
        self.original = original
        super().__init__(
            f"defect in view {view!r} evaluating criterion {criterion!r}, "
            f"postcondition {postcondition!r}: {type(original).__name__}: {original}"
        )


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


_SUBJECT_EXCERPT_LIMIT = 256


_NO_VALUE_AT_PATH = "\u2400 no value at path"
"""The stated marker for a path that selected nothing.

A missing field and a wrong extraction are different defects, and a reader
must be able to tell them apart without inferring it from an empty excerpt.
"""


def _subject_excerpt(value: Any) -> str:
    """A bounded excerpt of a projected subject — the area's excerpt rule."""
    text = str(value)
    if len(text) <= _SUBJECT_EXCERPT_LIMIT:
        return text
    return f"{text[: _SUBJECT_EXCERPT_LIMIT - 1]}\u2026"


@dataclass(frozen=True, slots=True)
class ObservedValue:
    """One obtained-value exemplar of a standings row.

    A bounded excerpt of what the service returned under the check's view,
    how many trials returned it, and whether the check held for them —
    stated facts, never a judgement beyond ``held``.
    """

    excerpt: str
    count: int
    held: bool


class FailureAxis(StrEnum):
    """Why a trial failed, on the companion's diagnostic axis (§1.4.5a).

    Diagnostic only: it never changes the arithmetic. Every trial counts in
    the denominator, whichever axis its failure lies on — the axis tells the
    developer whether the postcondition was judged and did not hold, or no
    testable value could be produced at all. A high transform/no-value share
    is itself a signal to read before the pass rate.

    Stated as a field rather than inferred from a reason string's prefix:
    the reason is author-facing prose, and parsing a display convention to
    recover structure is the sin the standings' structured rows removed.
    """

    CONDITION = "condition"
    TRANSFORM_NO_VALUE = "transform/no-value"


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    """One criterion's judgement of one response.

    Attributes:
        passed: Whether the response passed the criterion.
        reason: The failure reason on a fail (a view's transformation
            failure, or the first postcondition that did not hold);
            ``None`` on a pass.
        axis: The :class:`FailureAxis` ``reason`` lies on; ``None`` on a
            pass. Stated, never parsed back out of ``reason``.
        delivery_cause: On a failed delivery, why it failed — and the
            trial then lies on *no* axis, having never reached evaluation.
            ``None`` on a pass and on every evaluated failure. Stated
            rather than a third axis value, because the axis is the
            companion's (§1.4.5a) and a transport fact does not belong on
            it; the two fields are read together, never merged.
        outcomes: Per-postcondition ``(name, status)`` pairs in
            declaration order, with the family's three-valued
            :class:`Outcome` status.
        subjects: Per evaluated postcondition, ``(name, excerpt)`` — a
            bounded excerpt of the projected subject the check judged.
            Skipped checks (an earlier transform failed) have no entry.
    """

    passed: bool
    reason: str | None = None
    axis: FailureAxis | None = None
    delivery_cause: DeliveryCause | None = None
    outcomes: tuple[tuple[str, Outcome], ...] = ()
    subjects: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """The per-iteration bundle threaded through evaluation.

    Carries which input drove this sample and its position in the plan's
    input list. It replaces the module-global input channel the per-input
    dispatch once read: each trial is now judged against an explicit,
    self-contained context, so the per-sample unit is a pure function of its
    inputs — the groundwork for future bounded-parallel sampling. The
    ``index`` is what per-input expectations dispatch on (unique per input
    position, so equal input values are never conflated); ``input`` is the
    driving value, carried for diagnosis.
    """

    index: int
    input: Any


# mavai-ref: JVI-2GV36P= — do not remove (resolves in mavai-orchestrator)
def evaluate_trial(
    criterion: Criterion, views: TrialViews, context: EvaluationContext
) -> TrialEvaluation:
    """Evaluate one response (via its view cache) against one criterion.

    The trial is judged against exactly the postconditions that apply to
    this sample's input — :meth:`Criterion.postconditions_for` selects the
    always-on checks plus this input's per-input expectation, and the checks
    belonging to other inputs are not part of this trial at all. Applies
    them in declaration order to their named subjects; the criterion passes
    iff all hold. Every selected postcondition is evaluated (its outcome
    feeds result projections); the trial's ``reason`` is the first failure's.
    A :class:`TransformError` from a
    view's computation fails that postcondition and skips the rest — the
    views cache would fail them all identically. Any other exception
    escaping a view's transformation or a postcondition's evaluation is a
    defect: it is wrapped in a :class:`TrialDefectError` carrying the criterion,
    postcondition, and view, and re-raised for the sampling loop to diagnose
    and the orchestration layer to contain — never laundered into a failed
    trial.
    """
    outcomes: list[tuple[str, Outcome]] = []
    subjects: list[tuple[str, str]] = []
    first_required_reason: str | None = None
    first_optional_reason: str | None = None
    failed_optional = 0
    postconditions = list(criterion.postconditions_for(context.index))
    for index, postcondition in enumerate(postconditions):
        try:
            subject = views.get(postcondition.view)
        except TransformError as failure:
            # An unparseable response is not "within slack": a transform
            # failure hard-fails the trial regardless of any optional budget.
            reason = f"{_TRANSFORM_REASON_PREFIX} ({postcondition.view}): {failure}"
            outcomes.append((postcondition.name, Outcome.FAILED))
            outcomes.extend((later.name, Outcome.SKIPPED) for later in postconditions[index + 1 :])
            return TrialEvaluation(
                passed=False,
                reason=first_required_reason or reason,
                # An earlier required postcondition already failed on the
                # condition axis; this transform failure did not become the
                # stated reason, so the axis follows the reason, not the site.
                axis=(
                    FailureAxis.CONDITION
                    if first_required_reason is not None
                    else FailureAxis.TRANSFORM_NO_VALUE
                ),
                outcomes=tuple(outcomes),
                subjects=tuple(subjects),
            )
        except Exception as defect:
            raise TrialDefectError(
                view=postcondition.view,
                criterion=criterion.name,
                postcondition=postcondition.name,
                original=defect,
            ) from defect
        try:
            result = postcondition.evaluate(subject)
        except Exception as defect:
            raise TrialDefectError(
                view=postcondition.view,
                criterion=criterion.name,
                postcondition=postcondition.name,
                original=defect,
            ) from defect
        # The obtained value is what the check found where it looked. Only a
        # path-addressed check performs a projection, so only it can report
        # one; an unaddressed check judged the subject itself. Recording the
        # whole view here instead — as this did until 2026-08-03 — makes
        # every row show the same alphabetically-first field of the reply,
        # answering neither "what was returned at this path" nor "what was
        # the whole reply".
        subjects.append(
            (
                postcondition.name,
                _NO_VALUE_AT_PATH
                if result.no_value_at_path
                else _subject_excerpt(result.obtained if result.obtained is not None else subject),
            )
        )
        if result.passed:
            outcomes.append((postcondition.name, Outcome.PASSED))
        else:
            # Outcomes record what actually happened — a tolerated optional
            # failure is still FAILED here, so standings see reality, never
            # the softened verdict.
            outcomes.append((postcondition.name, Outcome.FAILED))
            reason = result.reason or f"postcondition {postcondition.name!r} not satisfied"
            if postcondition.required:
                if first_required_reason is None:
                    first_required_reason = reason
            else:
                failed_optional += 1
                if first_optional_reason is None:
                    first_optional_reason = reason
    optional_count = sum(1 for p in postconditions if not p.required)
    over_budget = failed_optional > criterion.optional_allowance(optional_count)
    trial_reason: str | None = None
    if first_required_reason is not None:
        trial_reason = first_required_reason
    elif over_budget:
        trial_reason = first_optional_reason
    return TrialEvaluation(
        passed=trial_reason is None,
        reason=trial_reason,
        axis=None if trial_reason is None else FailureAxis.CONDITION,
        outcomes=tuple(outcomes),
        subjects=tuple(subjects),
    )


@dataclass(slots=True)
class CriterionTally:
    """Accumulated per-criterion counts over a run's samples.

    Attributes:
        successes: Trials on which the criterion passed.
        trials: Total trials evaluated.
        failure_reasons: Distribution of failure reasons over failed trials.
        failure_axes: The :class:`FailureAxis` each observed reason lies
            on. A reason has exactly one axis, so this is a lookup beside
            the distribution rather than a second key on it — consumers
            that only count failures are untouched.
        delivery_causes: The :class:`DeliveryCause` of each observed
            reason that was a failed delivery, carried the same way and
            for the same reason. A reason is either a delivery or an
            evaluation, so a reason appears in at most one of the two
            lookups.
    """

    successes: int = 0
    trials: int = 0
    failure_reasons: Counter[str] = field(default_factory=Counter)
    failure_axes: dict[str, FailureAxis] = field(default_factory=dict)
    delivery_causes: dict[str, DeliveryCause] = field(default_factory=dict)

    def record(self, evaluation: TrialEvaluation) -> None:
        """Fold one trial's evaluation into the tally."""
        self.trials += 1
        if evaluation.passed:
            self.successes += 1
        else:
            reason = evaluation.reason or "unspecified"
            self.failure_reasons[reason] += 1
            if evaluation.axis is not None:
                self.failure_axes[reason] = evaluation.axis
            if evaluation.delivery_cause is not None:
                self.delivery_causes[reason] = evaluation.delivery_cause

    @property
    def observed_rate(self) -> float:
        """The observed pass rate. Read only after the run, when the tally
        has at least one trial."""
        return self.successes / self.trials

    @property
    def variance(self) -> float:
        """Sample variance of the observed pass rate — the dispersion a
        report shows beside the rate. Zero for an empty tally."""
        return proportion_variance(self.successes, self.trials)

    @property
    def standard_error(self) -> float:
        """Standard error of the observed pass rate. Zero for an empty tally."""
        return proportion_standard_error(self.successes, self.trials)


# mavai-ref: JVI-N9ZEY24 — do not remove (resolves in mavai-orchestrator)
@dataclass(frozen=True, slots=True)
class PostconditionStanding:
    """One check's descriptive tally over a run, for one input.

    Triage, not inference: counts and an observed fraction only. The run is
    sized for its criterion's claim, not for bounding each check, so a
    standing deliberately carries no confidence interval, no threshold, and
    no verdict — the criterion remains the only measured unit.

    Attributes:
        input_index: Position of the driving input in the plan's input list.
        postcondition: The check's name, as declared.
        passed: Trials on which the check held.
        failed: Trials on which it did not.
        skipped: Trials on which it went unevaluated (an earlier transform
            failure, or an undelivered response).
        optional: Whether the contract marks the check ``optional`` — stated
            with the tallies so every persisted standings shape can flag
            partial credit without consulting the contract.
        path: The structural address the check judges, when path-addressed —
            the by-path grouping key, stated, never derived from the name.
        form: The comparison form's domain name, when known.
        expected: A bounded excerpt of the declared operand, for display.
        observed: Obtained-value exemplars, failing exemplars first, distinct
            excerpts capped; ``elided`` counts the trials whose values were
            not exemplified.
    """

    input_index: int
    postcondition: str
    passed: int
    failed: int
    skipped: int
    optional: bool = False
    path: str | None = None
    form: str | None = None
    expected: str | None = None
    observed: tuple[ObservedValue, ...] = ()
    elided: int = 0

    @property
    def trials(self) -> int:
        """Trials this check was applicable to."""
        return self.passed + self.failed + self.skipped

    @property
    def observed_fraction(self) -> float:
        """The observed pass fraction over the check's applicable trials."""
        return self.passed / self.trials
