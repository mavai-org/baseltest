"""Per-trial evaluation: views, conjunction, failure reasons, tallies."""

import json
from dataclasses import replace
from typing import Any

import pytest

from baseltest.contract import (
    Criterion,
    CriterionTally,
    EvaluationContext,
    ServiceContract,
    TransformError,
    TrialDefectError,
    TrialViews,
    contains,
    equals,
    evaluate_trial,
    matches,
    one_of,
    satisfies,
)

# These evaluate_trial tests exercise general (non-per-input) postconditions,
# so any context serves — the input index only gates per-input expectations.
_CONTEXT = EvaluationContext(index=0, input=None)


def json_view(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as error:
        raise TransformError(f"response does not parse as json: {error}") from error


VIEWS = {"doc": json_view}


def views_for(response: str) -> TrialViews:
    return TrialViews(response, VIEWS)


def evaluate(criterion: Criterion, response: str):  # type: ignore[no-untyped-def]
    return evaluate_trial(criterion, views_for(response), _CONTEXT)


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
        assert evaluate_trial(first, views, _CONTEXT).passed
        assert evaluate_trial(second, views, _CONTEXT).passed
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

    def test_defect_in_view_is_wrapped_as_a_trial_defect(self) -> None:
        # A non-TransformError escaping a transform is a defect, not a failed
        # trial: it is wrapped in a TrialDefectError carrying the criterion,
        # postcondition, and view, with the original exception preserved.
        def broken(raw: str) -> Any:
            raise RuntimeError("bug in transformation")

        views = TrialViews("anything", {"doc": broken})
        criterion = Criterion(name="c", postconditions=(satisfies("any", bool, view="doc"),))
        with pytest.raises(TrialDefectError) as raised:
            evaluate_trial(criterion, views, _CONTEXT)
        defect = raised.value
        assert defect.view == "doc"
        assert defect.criterion == "c"
        assert defect.postcondition == "any"
        assert isinstance(defect.original, RuntimeError)
        assert str(defect.original) == "bug in transformation"

    def test_defect_in_postcondition_is_wrapped_as_a_trial_defect(self) -> None:
        criterion = Criterion(
            name="c",
            postconditions=(satisfies("buggy", lambda v: 1 / 0 > 0),),
        )
        with pytest.raises(TrialDefectError) as raised:
            evaluate(criterion, "anything")
        assert isinstance(raised.value.original, ZeroDivisionError)
        assert raised.value.postcondition == "buggy"


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


class TestPerInputGating:
    def test_per_input_expectation_gates_on_index_not_value(self) -> None:
        # Two inputs may share a value yet hold different expectations; the
        # trial's input INDEX selects which applies, so equal input values are
        # never conflated (the defect the module-global value channel had).
        criterion = Criterion(
            name="c",
            postconditions=(
                replace(equals("A"), applies_to_input=0),
                replace(equals("B"), applies_to_input=1),
            ),
        )
        shared = "duplicate-input-value"
        at_0 = EvaluationContext(index=0, input=shared)
        at_1 = EvaluationContext(index=1, input=shared)

        # Response "A" satisfies input 0's expectation but not input 1's —
        # decided by index, though both contexts carry the same input value.
        assert evaluate_trial(criterion, views_for("A"), at_0).passed
        assert not evaluate_trial(criterion, views_for("A"), at_1).passed
        # And symmetrically for "B".
        assert not evaluate_trial(criterion, views_for("B"), at_0).passed
        assert evaluate_trial(criterion, views_for("B"), at_1).passed

    def test_only_the_applicable_input_check_is_in_the_trial(self) -> None:
        # A sample is judged against exactly the checks that apply to its
        # input: the always-on ones and this input's per-input expectation.
        # The other inputs' checks are not part of the trial at all — they
        # are absent from the outcomes, not present-but-skipped.
        criterion = Criterion(
            name="c",
            postconditions=(
                contains("hi"),  # always-on
                replace(equals("A"), applies_to_input=0),
                replace(equals("B"), applies_to_input=1),
            ),
        )
        evaluation = evaluate_trial(
            criterion, views_for("hi A"), EvaluationContext(index=0, input="A")
        )
        names = [name for name, _ in evaluation.outcomes]
        assert names == ['contains "hi"', "equals 'A'"]  # input 1's check is absent
        assert "equals 'B'" not in names

    def test_applicable_input_check_can_fail_the_trial(self) -> None:
        # The check that applies is the one that decides the trial; the others
        # are simply not there to influence it either way.
        criterion = Criterion(
            name="c",
            postconditions=(
                replace(equals("A"), applies_to_input=0),
                replace(equals("B"), applies_to_input=1),
            ),
        )
        evaluation = evaluate_trial(
            criterion, views_for("X"), EvaluationContext(index=1, input="X")
        )
        assert not evaluation.passed
        assert dict(evaluation.outcomes) == {"equals 'B'": "failed"}  # only input 1's check

    def test_pooled_tally_is_a_conjunction_over_applicable_checks_only(self) -> None:
        # The criterion pools every input into one Bernoulli stream: each
        # sample contributes one trial, judged against its own input's checks.
        # Selecting the applicable subset per sample (rather than gating a
        # shared list) leaves the pooled successes/trials/failure count exactly
        # a conjunction over the applicable checks would give.
        criterion = Criterion(
            name="c",
            postconditions=(
                replace(equals("A"), applies_to_input=0),
                replace(equals("B"), applies_to_input=1),
            ),
        )
        tally = CriterionTally()
        tally.record(  # index 0 expects "A": holds
            evaluate_trial(criterion, views_for("A"), EvaluationContext(index=0, input="A"))
        )
        tally.record(  # index 0 expects "A": fails on "Z"
            evaluate_trial(criterion, views_for("Z"), EvaluationContext(index=0, input="A"))
        )
        tally.record(  # index 1 expects "B": holds
            evaluate_trial(criterion, views_for("B"), EvaluationContext(index=1, input="B"))
        )
        assert tally.trials == 3
        assert tally.successes == 2
        assert sum(tally.failure_reasons.values()) == 1

    def test_other_inputs_checks_do_not_resolve_their_views(self) -> None:
        # Because a non-applicable per-input check is not selected into the
        # trial, its view is never resolved — so a view that would transform-
        # fail on a sample the check does not belong to has no effect here.
        computed: list[str] = []

        def counting_view(raw: str) -> Any:
            computed.append(raw)
            return raw

        views = TrialViews("response", {"v": counting_view})
        criterion = Criterion(
            name="c",
            postconditions=(
                replace(satisfies("only-input-1", lambda v: True, view="v"), applies_to_input=1),
            ),
        )
        evaluation = evaluate_trial(criterion, views, EvaluationContext(index=0, input="other"))
        assert evaluation.outcomes == ()  # nothing applied to input 0
        assert computed == []  # so the view was never computed


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
