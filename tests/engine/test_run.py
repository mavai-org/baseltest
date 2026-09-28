"""Engine behaviour: preflight, sampling, verdicts, composite, mixed contracts."""

from itertools import count

import pytest

from baseltest.contract import (
    BaselineCount,
    Criterion,
    LatencyBar,
    LatencyBaseline,
    LatencyBound,
    ServiceContract,
    contains,
)
from baseltest.engine import (
    ConfigurationError,
    ConfigurationRefusedError,
    Intent,
    RunKind,
    RunPlan,
    derive_minimum_samples,
    execute,
    inputs_fingerprint,
)
from baseltest.engine.run.execute import _reduce_samples
from baseltest.engine.run.sample import _run_one_sample
from baseltest.statistics import ThresholdSource, Verdict, check_feasibility


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
        # observed 200/300 against 0.5: the exact binomial test demonstrates it
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.5)
        result = execute(contract_with((criterion,)), plan(300))
        assert result.criterion_results[0].verdict is Verdict.PASS
        assert result.composite is Verdict.PASS

    def test_missing_threshold_fails_and_run_completes(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.9)
        result = execute(contract_with((criterion,)), plan(300))
        assert result.criterion_results[0].verdict is Verdict.FAIL
        assert result.composite is Verdict.FAIL

    def test_verdict_is_the_exact_test_not_the_point_estimate(self) -> None:
        # observed 200/300 ≈ 0.667 exceeds 0.66, but compliance is not demonstrated
        criterion = Criterion(name="ok", postconditions=(contains("ok"),), threshold=0.66)
        result = execute(contract_with((criterion,)), plan(300))
        r = result.criterion_results[0]
        assert r.tally.observed_rate > 0.66
        assert r.decision is not None and r.decision.rule == "compliance/exact-binomial"
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
        with pytest.raises(ConfigurationRefusedError) as excinfo:
            execute(contract, plan(30))
        assert invocations == []
        assert excinfo.value.errors == (ConfigurationError.COMPLIANCE_INFEASIBLE,)
        (part,) = excinfo.value.parts
        assert (part.subject, part.limit) == ("c", 299)

    def test_test_larger_than_its_baseline_refused_whatever_the_intent(self) -> None:
        criterion = Criterion(
            name="c", postconditions=(contains("ok"),), baseline=BaselineCount(95, 100)
        )
        for intent in Intent:
            with pytest.raises(ConfigurationRefusedError) as excinfo:
                execute(contract_with((criterion,)), plan(101, intent=intent))
            assert excinfo.value.errors == (ConfigurationError.TEST_LARGER_THAN_BASELINE,)

    def test_the_whole_configuration_is_refused_naming_every_code_in_order(self) -> None:
        requirement = Criterion(name="req", postconditions=(contains("ok"),), threshold=0.999)
        regression = Criterion(
            name="reg", postconditions=(contains("ok"),), baseline=BaselineCount(95, 100)
        )
        with pytest.raises(ConfigurationRefusedError) as excinfo:
            execute(contract_with((requirement, regression)), plan(200))
        assert excinfo.value.errors == (
            ConfigurationError.TEST_LARGER_THAN_BASELINE,
            ConfigurationError.COMPLIANCE_INFEASIBLE,
        )

    def test_latency_test_size_is_judged_on_the_samplings(self) -> None:
        bar = LatencyBar(
            bounds=(LatencyBound("p50"),),
            origin=ThresholdSource.BASELINE_DERIVED,
            baseline=LatencyBaseline(tuple(range(1, 11)), samples=500),
        )
        criterion = Criterion(name="c", postconditions=(contains("ok"),))
        contract = ServiceContract(
            contract_id="svc", invoke=flaky_service(3), criteria=(criterion,), latency=bar
        )
        # 20 planned samples against a baseline run of 500, whose 10 successful
        # latencies are fewer than the test's: not refused.
        assert execute(contract, plan(20)).latency is not None
        with pytest.raises(ConfigurationRefusedError):
            execute(contract, plan(501))

    def test_explicit_latency_requirement_below_its_feasibility_is_refused(self) -> None:
        bar = LatencyBar(bounds=(LatencyBound("p95", 500),))
        criterion = Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5)
        contract = ServiceContract(
            contract_id="svc", invoke=flaky_service(3), criteria=(criterion,), latency=bar
        )
        with pytest.raises(ConfigurationRefusedError) as excinfo:
            execute(contract, plan(58))
        assert [part.subject for part in excinfo.value.parts] == ["latency p95"]

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
            check_feasibility(0.8, 1, 0.05).minimum_samples,
            check_feasibility(0.99, 1, 0.05).minimum_samples,
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


def exact_service(successes: int) -> object:
    """A service passing exactly the first `successes` invocations."""
    counter = count(1)

    def invoke(_input: str) -> str:
        return "ok" if next(counter) <= successes else "bad"

    return invoke


class TestRegressionPosture:
    """A criterion carrying its baseline evidence is judged by
    ``regression/fisher``: its cutoff is derived at the run's own size and the
    verdict is the raw observed count meeting it."""

    def _criterion(self, design_alternative_rate: float | None = None) -> Criterion:
        return Criterion(
            name="derived",
            postconditions=(contains("ok"),),
            baseline=BaselineCount(951, 1000),
            design_alternative_rate=design_alternative_rate,
        )

    def test_count_at_cutoff_passes(self) -> None:
        contract = ServiceContract(
            contract_id="svc", invoke=exact_service(91), criteria=(self._criterion(),)
        )
        result = execute(contract, RunPlan(samples=100, inputs=("a",)))
        r = result.criterion_results[0]
        assert r.decision is not None and r.decision.rule == "regression/fisher"
        assert r.verdict is Verdict.PASS
        assert result.composite is Verdict.PASS

    def test_count_below_cutoff_fails_and_names_the_criterion(self) -> None:
        contract = ServiceContract(
            contract_id="svc", invoke=exact_service(90), criteria=(self._criterion(),)
        )
        result = execute(contract, RunPlan(samples=100, inputs=("a",)))
        assert result.criterion_results[0].verdict is Verdict.FAIL
        assert result.overall is not None
        assert [t.id for t in result.overall.triggering] == ["derived"]

    def test_power_disclosure_names_the_two_powers_apart(self) -> None:
        contract = ServiceContract(
            contract_id="svc", invoke=exact_service(93), criteria=(self._criterion(0.90),)
        )
        power = execute(contract, RunPlan(samples=100, inputs=("a",))).criterion_results[0].power
        assert power is not None
        assert power.design_alternative_rate == 0.90
        assert power.design_power == pytest.approx(0.55, abs=0.01)
        assert power.resolved_power == pytest.approx(0.549, abs=0.001)
        assert power.minimum_detectable_degradation is not None

    def test_a_criterion_is_judged_against_a_requirement_or_a_baseline_not_both(self) -> None:
        with pytest.raises(ValueError, match="two criteria"):
            Criterion(
                name="c",
                postconditions=(contains("ok"),),
                threshold=0.9,
                baseline=BaselineCount(9, 10),
            )

    def test_a_requirement_and_a_baseline_are_two_criteria_composed(self) -> None:
        compliance = Criterion(name="req", postconditions=(contains("ok"),), threshold=0.80)
        regression = Criterion(
            name="reg", postconditions=(contains("ok"),), baseline=BaselineCount(951, 1000)
        )
        contract = ServiceContract(
            contract_id="svc", invoke=exact_service(90), criteria=(compliance, regression)
        )
        result = execute(contract, RunPlan(samples=100, inputs=("a",)))
        verdicts = {r.name: r.verdict for r in result.criterion_results}
        assert verdicts == {"req": Verdict.PASS, "reg": Verdict.FAIL}
        assert result.composite is Verdict.FAIL
        assert result.envelopes.false_compliance == pytest.approx(0.05)
        assert result.envelopes.false_degradation_signal == pytest.approx(0.05)


class TestReduceOrderIndependence:
    def test_reordered_outcomes_reduce_to_identical_artefacts(self) -> None:
        # The funnel folds by ordinal, so however the samples complete (serial
        # today, reordered/parallel later) the tallies, per-sample records, and
        # durations are byte-identical. Reducing forward vs reversed proves it.
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda text: text,  # echoes the input, so records differ by ordinal
            criteria=(Criterion(name="c", postconditions=(contains("a"),)),),
        )
        inputs = ("a", "b", "c")
        outcomes = [_run_one_sample(contract, i, inputs, record_samples=True) for i in range(6)]

        f_tallies, f_standings, f_successes, f_records, f_durations, f_tokens = _reduce_samples(
            contract, outcomes
        )
        r_tallies, r_standings, r_successes, r_records, r_durations, r_tokens = _reduce_samples(
            contract, list(reversed(outcomes))
        )

        assert f_records == r_records  # frozen SampleRecords, sequence included
        assert f_standings == r_standings  # frozen rows, order restored per input
        assert f_successes == r_successes
        assert f_tokens == r_tokens
        assert f_durations == r_durations
        assert f_tallies["c"].trials == r_tallies["c"].trials
        assert f_tallies["c"].successes == r_tallies["c"].successes
        assert f_tallies["c"].failure_reasons == r_tallies["c"].failure_reasons
        # Records are restored to run order, not left reversed.
        assert tuple(rec.content for rec in f_records) == ("a", "b", "c", "a", "b", "c")
