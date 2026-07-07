"""Per-trial evaluation: views, conjunction, failure reasons, tallies."""

import json
from typing import Any

import pytest

from baseltest.contract import (
    Criterion,
    CriterionTally,
    ServiceContract,
    TransformError,
    TrialViews,
    contains,
    equals,
    evaluate_trial,
    matches,
    one_of,
    satisfies,
)


def json_view(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as error:
        raise TransformError(f"response does not parse as json: {error}") from error


VIEWS = {"doc": json_view}


def views_for(response: str) -> TrialViews:
    return TrialViews(response, VIEWS)


def evaluate(criterion: Criterion, response: str):  # type: ignore[no-untyped-def]
    return evaluate_trial(criterion, views_for(response))


class TestStringForms:
    def test_equals_passes_on_exact_match(self) -> None:
        criterion = Criterion(name="c", postconditions=(equals("hello"),))
        assert evaluate(criterion, "hello").passed

    def test_equals_fails_with_reason(self) -> None:
        criterion = Criterion(name="c", postconditions=(equals("hello"),))
        evaluation = evaluate(criterion, "goodbye")
        assert not evaluation.passed
        assert evaluation.reason is not None and "does not equal" in evaluation.reason

    def test_one_of(self) -> None:
        criterion = Criterion(name="c", postconditions=(one_of(["a", "b"]),))
        assert evaluate(criterion, "b").passed
        assert not evaluate(criterion, "c").passed

    def test_contains(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("hello"),))
        assert evaluate(criterion, "why hello there").passed
        assert not evaluate(criterion, "goodbye").passed

    def test_matches_searches_anywhere(self) -> None:
        criterion = Criterion(name="c", postconditions=(matches(r"RF-\d{8}"),))
        assert evaluate(criterion, "your ref is RF-12345678, thanks").passed
        assert not evaluate(criterion, "no reference here").passed

    def test_conjunction_requires_every_form(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("case"), contains("refund")))
        assert evaluate(criterion, "refund case 12").passed
        evaluation = evaluate(criterion, "refund only")
        assert not evaluation.passed
        assert evaluation.reason is not None and "case" in evaluation.reason


class TestViews:
    def test_satisfies_receives_the_named_view(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("status ok", lambda v: v["status"] == "ok", view="doc"),),
        )
        assert evaluate(criterion, '{"status": "ok"}').passed

    def test_view_failure_is_a_failed_trial_with_transform_reason(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("any", lambda v: True, view="doc"),),
        )
        evaluation = evaluate(criterion, "not json {")
        assert not evaluation.passed
        assert evaluation.reason is not None
        assert evaluation.reason.startswith("transform failed (doc)")

    def test_raw_is_the_default_subject_even_when_views_exist(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(contains('"ok"'),),
        )
        assert evaluate(criterion, '{"status": "ok"}').passed

    def test_view_computed_once_and_shared_within_a_trial(self) -> None:
        calls = []

        def counting_view(raw: str) -> Any:
            calls.append(raw)
            return json.loads(raw)

        views = TrialViews('{"a": 1}', {"doc": counting_view})
        first = Criterion(
            name="first", postconditions=(satisfies("has a", lambda v: "a" in v, view="doc"),)
        )
        second = Criterion(name="second", postconditions=(satisfies("truthy", bool, view="doc"),))
        assert evaluate_trial(first, views).passed
        assert evaluate_trial(second, views).passed
        assert len(calls) == 1  # one computation, both criteria served

    def test_string_form_on_structured_view_is_a_type_failure(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("x", view="doc"),))
        evaluation = evaluate(criterion, '{"a": 1}')
        assert not evaluation.passed
        assert evaluation.reason is not None and "not text" in evaluation.reason

    def test_undeclared_view_is_rejected_by_the_contract(self) -> None:
        criterion = Criterion(name="c", postconditions=(satisfies("any", bool, view="ghost"),))
        with pytest.raises(ValueError, match="undeclared view"):
            ServiceContract(contract_id="svc", invoke=lambda v: v, criteria=(criterion,))

    def test_raw_cannot_be_declared_as_a_view(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("x"),))
        with pytest.raises(ValueError, match="reserved"):
            ServiceContract(
                contract_id="svc",
                invoke=lambda v: v,
                criteria=(criterion,),
                views={"raw": lambda raw: raw},
            )

    def test_defect_in_view_propagates(self) -> None:
        def broken(raw: str) -> Any:
            raise RuntimeError("bug in transformation")

        views = TrialViews("anything", {"doc": broken})
        criterion = Criterion(name="c", postconditions=(satisfies("any", bool, view="doc"),))
        with pytest.raises(RuntimeError):
            evaluate_trial(criterion, views)

    def test_defect_in_postcondition_propagates(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("buggy", lambda v: 1 / 0 > 0),),
        )
        with pytest.raises(ZeroDivisionError):
            evaluate(criterion, "anything")


class TestTally:
    def test_tally_counts_and_reasons(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("ok"),))
        tally = CriterionTally()
        for response in ["ok", "ok", "nope", "ok", "nah"]:
            tally.record(evaluate(criterion, response))
        assert tally.trials == 5
        assert tally.successes == 3
        assert tally.observed_rate == 0.6
        assert sum(tally.failure_reasons.values()) == 2

    def test_view_failures_are_attributed_distinctly(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("truthy", bool, view="doc"),),
        )
        tally = CriterionTally()
        tally.record(evaluate(criterion, "not json"))
        tally.record(evaluate(criterion, "0"))
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
