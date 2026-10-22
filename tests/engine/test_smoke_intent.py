"""Smoke intent through the engine: a requirement decided by its own rule,
while bar attainment stays a fact about the experiment."""

from itertools import count

import pytest

from baseltest.contract import BaselineCount, Criterion, ServiceContract, contains
from baseltest.engine import (
    BarAttainment,
    ConfigurationRefusedError,
    DecisionRule,
    Intent,
    RunKind,
    RunPlan,
    SmokeComplianceVerdict,
    Verdict,
    bar_attainment,
    execute,
)


def _contract(misses: int, threshold: float = 0.99) -> ServiceContract[str]:
    """A service that misses its first ``misses`` samples and passes the rest."""
    counter = count(1)
    return ServiceContract(
        contract_id="guardrail",
        invoke=lambda _value: "bad" if next(counter) <= misses else "ok",
        criteria=(
            Criterion(name="rejects", postconditions=(contains("ok"),), threshold=threshold),
        ),
    )


def _smoke(contract: ServiceContract[str], samples: int = 100) -> SmokeComplianceVerdict:
    result = execute(contract, RunPlan(samples=samples, inputs=("a",), intent=Intent.SMOKE))
    decision = result.criterion_results[0].decision
    assert isinstance(decision, SmokeComplianceVerdict)
    return decision


class TestTheWorkshopCase:
    """0.99 at alpha 0.05 over 100 samples: VERIFICATION refuses it (PASS
    needs 299); SMOKE runs it and needs 97 passes."""

    def test_an_always_succeeding_service_passes(self) -> None:
        result = execute(
            _contract(misses=0), RunPlan(samples=100, inputs=("a",), intent=Intent.SMOKE)
        )
        decision = result.criterion_results[0].decision
        assert isinstance(decision, SmokeComplianceVerdict)
        # No early termination: every planned sample runs.
        assert decision.trials == 100 and decision.successes == 100
        assert decision.rule is DecisionRule.COMPLIANCE_SMOKE_EXACT_BINOMIAL
        assert decision.required_pass == 97
        assert decision.verdict is Verdict.PASS
        assert result.composite is Verdict.PASS

    def test_three_misses_still_pass(self) -> None:
        assert _smoke(_contract(misses=3)).verdict is Verdict.PASS

    def test_four_misses_are_evidence_of_falling_short(self) -> None:
        decision = _smoke(_contract(misses=4))
        assert decision.verdict is Verdict.FAIL
        assert decision.p_value <= decision.alpha

    def test_verification_still_refuses_the_design(self) -> None:
        with pytest.raises(ConfigurationRefusedError):
            execute(_contract(misses=0), RunPlan(samples=100, inputs=("a",)))


def test_an_empirical_criterion_is_decided_by_fisher_under_either_intent() -> None:
    criterion = Criterion(
        name="extraction", postconditions=(contains("ok"),), baseline=BaselineCount(951, 1000)
    )
    contract = ServiceContract(contract_id="svc", invoke=lambda _v: "ok", criteria=(criterion,))
    for intent in Intent:
        result = execute(contract, RunPlan(samples=100, inputs=("a",), intent=intent))
        decision = result.criterion_results[0].decision
        assert decision is not None and decision.rule is DecisionRule.REGRESSION_FISHER


class TestBarAttainmentStaysOnTheExactBinomial:
    """Whether a bar was met, or could have been, is a fact about the
    experiment: a smoke run's attainment is exactly the verification rule's."""

    @pytest.mark.parametrize(
        ("threshold", "samples", "misses", "expected"),
        [
            (0.99, 100, 0, BarAttainment.UNSUPPORTABLE),  # smoke PASS; no count can pass
            (0.99, 100, 4, BarAttainment.UNSUPPORTABLE),  # smoke FAIL
            (0.95, 150, 3, BarAttainment.NOT_MET),  # smoke PASS; k_min is 148
            (0.95, 150, 2, BarAttainment.MET),
            (0.95, 150, 13, BarAttainment.NOT_MET),  # smoke FAIL
        ],
    )
    def test_attainment_is_unchanged_by_smoke_intent(
        self, threshold: float, samples: int, misses: int, expected: BarAttainment
    ) -> None:
        standings = {}
        for intent in Intent:
            result = execute(
                _contract(misses, threshold),
                RunPlan(samples=samples, inputs=("a",), kind=RunKind.MEASURE, intent=intent),
            )
            standings[intent] = bar_attainment(result.criterion_results[0])
        assert standings[Intent.SMOKE] is standings[Intent.VERIFICATION] is expected

    def test_a_smoke_pass_is_not_a_met_bar(self) -> None:
        result = execute(
            _contract(misses=0), RunPlan(samples=100, inputs=("a",), intent=Intent.SMOKE)
        )
        criterion = result.criterion_results[0]
        assert criterion.verdict is Verdict.PASS
        assert bar_attainment(criterion) is BarAttainment.UNSUPPORTABLE
