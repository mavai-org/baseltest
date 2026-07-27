"""Partial-credit acceptance: required/optional checks and the slack budget.

A trial passes its criterion iff every applicable required check holds and
no more applicable optional checks fail than the criterion's declared
slack allows. No slack declared means none may fail — the double opt-in.
The trial stays one Bernoulli outcome; only the predicate changes, and the
recorded per-check outcomes stay true to what happened.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from baseltest.contract import (
    Criterion,
    EvaluationContext,
    OptionalSlack,
    Outcome,
    TrialViews,
    contains,
    evaluate_trial,
)
from baseltest.contract.model import TransformError

CONTEXT = EvaluationContext(index=0, input="a")


def optional(postcondition):  # type: ignore[no-untyped-def]
    return replace(postcondition, required=False)


def views(response: str = "hello world", **transforms):  # type: ignore[no-untyped-def]
    return TrialViews(response, transforms)


class TestOptionalSlack:
    def test_exactly_one_shape(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            OptionalSlack()
        with pytest.raises(ValueError, match="exactly one"):
            OptionalSlack(count=1, percent=Decimal("20"))

    def test_count_allowance_is_the_count(self) -> None:
        assert OptionalSlack(count=2).allowance(7) == 2

    def test_percent_resolves_by_floor(self) -> None:
        assert OptionalSlack(percent=Decimal("20")).allowance(7) == 1  # floor(1.4)
        assert OptionalSlack(percent=Decimal("29")).allowance(100) == 29  # no float artefact
        assert OptionalSlack(percent=Decimal("100")).allowance(3) == 3

    def test_negative_shapes_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            OptionalSlack(count=-1)
        with pytest.raises(ValueError, match="non-negative"):
            OptionalSlack(percent=Decimal("-5"))


class TestPredicate:
    def test_optional_alone_weakens_nothing(self) -> None:
        # The double opt-in: no slack declared -> budget 0.
        criterion = Criterion(
            name="c", postconditions=(contains("hello"), optional(contains("absent")))
        )
        evaluation = evaluate_trial(criterion, views(), CONTEXT)
        assert not evaluation.passed

    def test_optional_failures_within_budget_pass_the_trial(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(contains("hello"), optional(contains("absent"))),
            optional_slack=OptionalSlack(count=1),
        )
        evaluation = evaluate_trial(criterion, views(), CONTEXT)
        assert evaluation.passed
        assert evaluation.reason is None

    def test_outcomes_record_the_tolerated_failure(self) -> None:
        # Standings see reality: a tolerated optional failure is still FAILED.
        criterion = Criterion(
            name="c",
            postconditions=(contains("hello"), optional(contains("absent"))),
            optional_slack=OptionalSlack(count=1),
        )
        evaluation = evaluate_trial(criterion, views(), CONTEXT)
        assert evaluation.outcomes[1][1] is Outcome.FAILED

    def test_over_budget_fails_with_the_first_optional_reason(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(optional(contains("absent")), optional(contains("missing"))),
            optional_slack=OptionalSlack(count=1),
        )
        evaluation = evaluate_trial(criterion, views(), CONTEXT)
        assert not evaluation.passed
        assert evaluation.reason is not None and "absent" in evaluation.reason

    def test_a_required_failure_outranks_a_tolerated_optional_one(self) -> None:
        # The trial's reason names the non-negotiable failure even when an
        # optional check failed first in declaration order.
        criterion = Criterion(
            name="c",
            postconditions=(optional(contains("absent")), contains("gone")),
            optional_slack=OptionalSlack(count=5),
        )
        evaluation = evaluate_trial(criterion, views(), CONTEXT)
        assert not evaluation.passed
        assert evaluation.reason is not None and "gone" in evaluation.reason

    def test_percent_budget_applies_to_the_applicable_optional_count(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(
                optional(contains("hello")),
                optional(contains("world")),
                optional(contains("absent")),
            ),
            optional_slack=OptionalSlack(percent=Decimal("40")),
        )
        # floor(40% of 3) = 1 allowed; exactly one fails.
        assert evaluate_trial(criterion, views(), CONTEXT).passed

    def test_transform_failure_hard_fails_regardless_of_budget(self) -> None:
        def explode(_response: str) -> str:
            raise TransformError("not parseable")

        criterion = Criterion(
            name="c",
            postconditions=(optional(replace(contains("x"), view="doc")), contains("hello")),
            optional_slack=OptionalSlack(count=5),
        )
        evaluation = evaluate_trial(criterion, views(doc=explode), CONTEXT)
        assert not evaluation.passed
        assert evaluation.reason is not None and "transform failed" in evaluation.reason
        # The later required check is recorded skipped, not run.
        assert evaluation.outcomes[1][1] is Outcome.SKIPPED
