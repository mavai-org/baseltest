"""Per-trial evaluation: transform stage, conjunction, failure reasons, tallies."""

import json
from typing import Any

import pytest

from baseltest.contract import (
    Criterion,
    CriterionTally,
    TransformError,
    contains,
    equals,
    evaluate_trial,
    matches,
    one_of,
    satisfies,
)


def json_transform(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as error:
        raise TransformError(f"response does not parse as json: {error}") from error


class TestStringForms:
    def test_equals_passes_on_exact_match(self) -> None:
        criterion = Criterion(name="c", postconditions=(equals("hello"),))
        assert evaluate_trial(criterion, "hello").passed

    def test_equals_fails_with_reason(self) -> None:
        criterion = Criterion(name="c", postconditions=(equals("hello"),))
        evaluation = evaluate_trial(criterion, "goodbye")
        assert not evaluation.passed
        assert evaluation.reason is not None and "does not equal" in evaluation.reason

    def test_one_of(self) -> None:
        criterion = Criterion(name="c", postconditions=(one_of(["a", "b"]),))
        assert evaluate_trial(criterion, "b").passed
        assert not evaluate_trial(criterion, "c").passed

    def test_contains(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("hello"),))
        assert evaluate_trial(criterion, "why hello there").passed
        assert not evaluate_trial(criterion, "goodbye").passed

    def test_matches_searches_anywhere(self) -> None:
        criterion = Criterion(name="c", postconditions=(matches(r"RF-\d{8}"),))
        assert evaluate_trial(criterion, "your ref is RF-12345678, thanks").passed
        assert not evaluate_trial(criterion, "no reference here").passed

    def test_conjunction_requires_every_form(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("case"), contains("refund")))
        assert evaluate_trial(criterion, "refund case 12").passed
        evaluation = evaluate_trial(criterion, "refund only")
        assert not evaluation.passed
        assert evaluation.reason is not None and "case" in evaluation.reason

    def test_first_failing_form_supplies_the_reason(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("alpha"), contains("beta")))
        evaluation = evaluate_trial(criterion, "beta only")
        assert evaluation.reason is not None and "alpha" in evaluation.reason


class TestTransformStage:
    def test_satisfies_receives_transformed_value(self) -> None:
        criterion = Criterion(
            name="c",
            transform=json_transform,
            postconditions=(satisfies("status confirmed", lambda v: v["status"] == "ok"),),
        )
        assert evaluate_trial(criterion, '{"status": "ok"}').passed

    def test_transform_failure_is_a_failed_trial_with_transform_reason(self) -> None:
        criterion = Criterion(
            name="c",
            transform=json_transform,
            postconditions=(satisfies("any", lambda v: True),),
        )
        evaluation = evaluate_trial(criterion, "not json {")
        assert not evaluation.passed
        assert evaluation.reason is not None
        assert evaluation.reason.startswith("transform failed")

    def test_string_forms_judge_the_raw_response_even_under_transform(self) -> None:
        criterion = Criterion(
            name="c",
            transform=json_transform,
            postconditions=(contains('"ok"'),),
        )
        assert evaluate_trial(criterion, '{"status": "ok"}').passed

    def test_defect_in_transform_propagates(self) -> None:
        def broken(raw: str) -> Any:
            raise RuntimeError("bug in transform")

        criterion = Criterion(
            name="c", transform=broken, postconditions=(satisfies("any", lambda v: True),)
        )
        with pytest.raises(RuntimeError):
            evaluate_trial(criterion, "anything")

    def test_defect_in_postcondition_propagates(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("buggy", lambda v: 1 / 0 > 0),),
        )
        with pytest.raises(ZeroDivisionError):
            evaluate_trial(criterion, "anything")


class TestTally:
    def test_tally_counts_and_reasons(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("ok"),))
        tally = CriterionTally()
        for response in ["ok", "ok", "nope", "ok", "nah"]:
            tally.record(evaluate_trial(criterion, response))
        assert tally.trials == 5
        assert tally.successes == 3
        assert tally.observed_rate == 0.6
        assert sum(tally.failure_reasons.values()) == 2

    def test_transform_failures_are_attributed_distinctly(self) -> None:
        criterion = Criterion(
            name="c",
            transform=json_transform,
            postconditions=(satisfies("truthy", bool),),
        )
        tally = CriterionTally()
        tally.record(evaluate_trial(criterion, "not json"))
        tally.record(evaluate_trial(criterion, "0"))
        reasons = list(tally.failure_reasons)
        assert any(r.startswith("transform failed") for r in reasons)
        assert any("truthy" in r for r in reasons)


class TestModelValidation:
    def test_threshold_range_enforced(self) -> None:
        with pytest.raises(ValueError):
            Criterion(name="c", postconditions=(contains("x"),), threshold=1.0)

    def test_empty_postconditions_rejected(self) -> None:
        with pytest.raises(ValueError):
            Criterion(name="c", postconditions=())

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            Criterion(name="", postconditions=(contains("x"),))
