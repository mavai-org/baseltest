"""Engine behaviour: preflight, sampling, verdicts, composite, mixed contracts."""

from itertools import count

import pytest

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import (
    InfeasibleRunError,
    Intent,
    RunKind,
    RunPlan,
    derive_minimum_samples,
    execute,
    inputs_fingerprint,
)
from baseltest.statistics import check_feasibility
from baseltest.statistics.verdict import Verdict


def flaky_service(period: int) -> object:
    """A service failing every `period`-th invocation."""
    counter = count(1)

    def invoke(_input: str) -> str:
        n = next(counter)
        return "bad" if n % period == 0 else "ok"

    return invoke


def contract_with(criteria: tuple[Criterion, ...]) -> ServiceContract:
    return ServiceContract(
        contract_id="svc",
        invoke=flaky_service(3),
        criteria=criteria,  # type: ignore[arg-type]
    )


def plan(samples: int, **kwargs: object) -> RunPlan:
    return RunPlan(samples=samples, inputs=("a", "b"), **kwargs)  # type: ignore[arg-type]


class TestVerdicts:
    def test_clearing_threshold_passes(self) -> None:
        # observed ~2/3 against 0.5: Wilson lower bound clears at 300 samples
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.5)
        result = execute(contract_with((criterion,)), plan(300))
        assert result.criterion_results[0].verdict is Verdict.PASS
        assert result.composite is Verdict.PASS

    def test_missing_threshold_fails_and_run_completes(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.9)
        result = execute(contract_with((criterion,)), plan(300))
        assert result.criterion_results[0].verdict is Verdict.FAIL
        assert result.composite is Verdict.FAIL

    def test_verdict_is_bound_based_not_point_estimate(self) -> None:
        # observed 2/3 ≈ 0.667 exceeds 0.66, but the lower bound at 300 does not
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.66)
        result = execute(contract_with((criterion,)), plan(300))
        r = result.criterion_results[0]
        assert r.tally.observed_rate > 0.66
        assert r.lower_bound is not None and r.lower_bound < 0.66
        assert r.verdict is Verdict.FAIL


class TestMultiCriterion:
    def test_streams_judged_independently_and_composite_fails_on_any(self) -> None:
        passing = Criterion(name="lenient", postconditions=(contains("o"),), threshold=0.5)
        failing = Criterion(name="strict", postconditions=(contains("ok"),), threshold=0.9)
        result = execute(contract_with((passing, failing)), plan(300))
        by_name = {r.name: r for r in result.criterion_results}
        assert by_name["lenient"].verdict is Verdict.PASS
        assert by_name["strict"].verdict is Verdict.FAIL
        assert result.composite is Verdict.FAIL

    def test_mixed_contract_characterises_unthresholded(self) -> None:
        judged = Criterion(name="judged", postconditions=(contains("o"),), threshold=0.5)
        measured = Criterion(name="measured", postconditions=(contains("ok"),))
        result = execute(contract_with((judged, measured)), plan(300))
        by_name = {r.name: r for r in result.criterion_results}
        assert by_name["judged"].verdict is Verdict.PASS
        assert by_name["measured"].verdict is None
        assert by_name["measured"].lower_bound is None
        assert by_name["measured"].tally.trials == 300
        assert result.composite is Verdict.PASS

    def test_no_thresholds_means_no_composite(self) -> None:
        measured = Criterion(name="measured", postconditions=(contains("ok"),))
        result = execute(contract_with((measured,)), plan(50, kind=RunKind.MEASURE))
        assert result.composite is None


class TestPreflight:
    def test_infeasible_verification_refused_before_any_invocation(self) -> None:
        invocations = []

        def invoke(value: str) -> str:
            invocations.append(value)
            return value

        criterion = Criterion(name="c", postconditions=(contains("x"),), threshold=0.99)
        contract = ServiceContract(contract_id="svc", invoke=invoke, criteria=(criterion,))
        with pytest.raises(InfeasibleRunError) as excinfo:
            execute(contract, plan(30))
        assert invocations == []
        assert excinfo.value.governing_minimum > 30
        assert excinfo.value.infeasible[0].name == "c"

    def test_smoke_intent_runs_anyway(self) -> None:
        criterion = Criterion(name="c", postconditions=(contains("ok"),), threshold=0.99)
        result = execute(contract_with((criterion,)), plan(30, intent=Intent.SMOKE))
        assert result.criterion_results[0].tally.trials == 30

    def test_governing_minimum_is_largest_per_criterion(self) -> None:
        lax = Criterion(name="lax", postconditions=(contains("ok"),), threshold=0.8)
        strict = Criterion(name="strict", postconditions=(contains("ok"),), threshold=0.99)
        contract = contract_with((lax, strict))
        derived = derive_minimum_samples(contract)
        assert derived == max(
            check_feasibility(1, 0.8, 0.95).minimum_samples,
            check_feasibility(1, 0.99, 0.95).minimum_samples,
        )

    def test_derivation_requires_a_threshold(self) -> None:
        measured = Criterion(name="m", postconditions=(contains("ok"),))
        with pytest.raises(ValueError):
            derive_minimum_samples(contract_with((measured,)))


class TestRunMechanics:
    def test_defect_in_invocation_aborts(self) -> None:
        def invoke(_value: str) -> str:
            raise ConnectionError("service unreachable")

        criterion = Criterion(name="c", postconditions=(contains("x"),))
        contract = ServiceContract(contract_id="svc", invoke=invoke, criteria=(criterion,))
        with pytest.raises(ConnectionError):
            execute(contract, plan(10, kind=RunKind.MEASURE))

    def test_inputs_cycle_round_robin(self) -> None:
        seen: list[str] = []

        def invoke(value: str) -> str:
            seen.append(value)
            return value

        criterion = Criterion(name="c", postconditions=(contains("a"),))
        contract = ServiceContract(contract_id="svc", invoke=invoke, criteria=(criterion,))
        execute(contract, RunPlan(samples=5, inputs=("a", "b"), kind=RunKind.MEASURE))
        assert seen == ["a", "b", "a", "b", "a"]

    def test_inputs_fingerprint_is_order_insensitive(self) -> None:
        assert inputs_fingerprint(["b", "a"]) == inputs_fingerprint(["a", "b"])
        assert inputs_fingerprint(["a"]) != inputs_fingerprint(["a", "b"])


class TestProgressCallback:
    def test_on_sample_observes_every_sample(self) -> None:
        seen: list[tuple[int, int]] = []
        criterion = Criterion(name="c", postconditions=(contains("a"),))
        contract = ServiceContract(contract_id="svc", invoke=lambda v: v, criteria=(criterion,))
        execute(
            contract,
            RunPlan(samples=4, inputs=("a",), kind=RunKind.MEASURE),
            on_sample=lambda done, total: seen.append((done, total)),
        )
        assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]
