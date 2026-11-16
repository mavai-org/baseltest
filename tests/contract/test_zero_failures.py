"""The zero-failures criterion: an observational criterion that must hold on
every trial, decided by no rule (§1.4.5)."""

from itertools import count

import pytest

from baseltest.contract import BaselineCount, Criterion, ServiceContract, contains
from baseltest.engine import (
    BarAttainment,
    Intent,
    ObservationalVerdict,
    RunKind,
    RunPlan,
    Verdict,
    bar_attainment,
    execute,
)


def criterion(**overrides: object) -> Criterion:
    fields: dict[str, object] = {
        "name": "never-insults",
        "postconditions": (contains("ok"),),
        "zero_failures": True,
    }
    fields.update(overrides)
    return Criterion(**fields)  # type: ignore[arg-type]


def failing_first(misses: int) -> object:
    counter = count()
    return lambda _value: "bad" if next(counter) < misses else "ok"


def run(misses: int, *criteria: Criterion, kind: RunKind = RunKind.TEST, samples: int = 20):  # type: ignore[no-untyped-def]
    contract = ServiceContract(
        contract_id="greeting",
        invoke=failing_first(misses),  # type: ignore[arg-type]
        criteria=criteria or (criterion(),),
    )
    return execute(contract, RunPlan(samples=samples, inputs=("a",), kind=kind))


class TestTheCriterion:
    def test_it_is_judged_by_no_rule(self) -> None:
        zero = criterion()
        assert zero.is_judged
        assert zero.rule_under(Intent.VERIFICATION) is None
        assert zero.rule_under(Intent.SMOKE) is None

    @pytest.mark.parametrize(
        ("overrides", "what"),
        [
            ({"threshold": 0.9}, "threshold"),
            ({"baseline": BaselineCount(90, 100)}, "baseline"),
            ({"confidence": 0.99}, "confidence level"),
        ],
    )
    def test_nothing_that_parameterises_a_rate_stands_beside_it(
        self, overrides: dict[str, object], what: str
    ) -> None:
        with pytest.raises(ValueError, match=f"a zero-failures criterion takes no {what}"):
            criterion(**overrides)

    def test_a_design_alternative_rate_is_refused(self) -> None:
        with pytest.raises(ValueError, match="takes no design alternative rate"):
            criterion(design_alternative_rate=0.8)

    def test_false_is_an_ordinary_criterion(self) -> None:
        ordinary = criterion(zero_failures=False, threshold=0.9)
        assert ordinary.threshold == 0.9


class TestTheRun:
    def test_no_failure_passes(self) -> None:
        result = run(0)
        (only,) = result.criterion_results
        assert isinstance(only.decision, ObservationalVerdict)
        assert only.verdict is Verdict.PASS
        assert only.decision.failures == 0
        assert only.lower_bound is None and only.power is None
        assert result.composite is Verdict.PASS

    def test_one_failure_fails(self) -> None:
        result = run(1)
        (only,) = result.criterion_results
        assert only.verdict is Verdict.FAIL
        assert isinstance(only.decision, ObservationalVerdict)
        assert only.decision.failures == 1
        assert result.composite is Verdict.FAIL

    def test_it_enters_neither_envelope(self) -> None:
        result = run(0)
        assert result.envelopes.false_compliance is None
        assert result.envelopes.false_degradation_signal is None

    def test_beside_a_requirement_only_the_requirement_enters_an_envelope(self) -> None:
        requirement = Criterion(name="relevant", postconditions=(contains("ok"),), threshold=0.5)
        result = run(0, criterion(), requirement)
        assert result.envelopes.false_compliance == pytest.approx(0.05)
        assert result.envelopes.false_degradation_signal is None

    def test_one_failure_fails_the_composite_beside_a_passing_requirement(self) -> None:
        requirement = Criterion(name="relevant", postconditions=(contains("ok"),), threshold=0.5)
        result = run(1, criterion(), requirement)
        verdicts = {r.name: r.verdict for r in result.criterion_results}
        assert verdicts == {"never-insults": Verdict.FAIL, "relevant": Verdict.PASS}
        assert result.composite is Verdict.FAIL

    def test_under_measure_the_bar_is_met_or_not_met_never_unsupportable(self) -> None:
        met = run(0, kind=RunKind.MEASURE, samples=3)
        missed = run(1, kind=RunKind.MEASURE, samples=3)
        assert bar_attainment(met.criterion_results[0]) is BarAttainment.MET
        assert bar_attainment(missed.criterion_results[0]) is BarAttainment.NOT_MET
