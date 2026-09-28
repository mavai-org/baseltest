"""The shared latency summary: passing-samples basis, gating, sorted vector."""

from baseltest.contract import (
    Criterion,
    LatencyBar,
    LatencyBaseline,
    LatencyBound,
    ServiceContract,
    contains,
)
from baseltest.engine import (
    Intent,
    RunKind,
    RunPlan,
    SampleRecord,
    Verdict,
    evaluate_latency,
    execute,
    latency_block,
    plan_latency,
)
from baseltest.statistics import ThresholdSource


def sample(ms: int, passed: bool = True) -> SampleRecord:
    return SampleRecord(
        input_index=0,
        postconditions=(("has content", "passed" if passed else "failed"),),
        execution_time_ms=ms,
        content="ok",
        passed=passed,
    )


class TestLatencyBlock:
    def test_none_when_nothing_passed(self) -> None:
        assert latency_block((sample(40, passed=False),)) is None
        assert latency_block(()) is None

    def test_only_passing_samples_contribute(self) -> None:
        block = latency_block((sample(40), sample(999, passed=False), sample(20)))
        assert block is not None
        assert block.basis == "passing-samples"
        assert block.contributing_samples == 2
        assert block.total_samples == 3
        assert block.sorted_passing_latencies_ms == (20, 40)

    def test_vector_is_ascending_and_matches_contributing_count(self) -> None:
        block = latency_block(tuple(sample(ms) for ms in (300, 100, 200)))
        assert block is not None
        assert block.sorted_passing_latencies_ms == (100, 200, 300)
        assert len(block.sorted_passing_latencies_ms) == block.contributing_samples

    def test_percentiles_are_gated_by_contributing_samples(self) -> None:
        # 15 passing samples support p50 and p90; p95 needs 20, p99 needs 100.
        block = latency_block(tuple(sample(ms) for ms in range(10, 160, 10)))
        assert block is not None
        assert [key for key, _ in block.percentiles] == ["p50Ms", "p90Ms"]

    def test_percentiles_are_nearest_rank_order_statistics(self) -> None:
        # 20 samples 10..200: p50 is the 10th (100), p90 the 18th (180),
        # p95 the 19th (190); each an observed value, no interpolation.
        block = latency_block(tuple(sample(ms) for ms in range(10, 210, 10)))
        assert block is not None
        assert dict(block.percentiles) == {"p50Ms": 100, "p90Ms": 180, "p95Ms": 190}

    def test_below_the_median_minimum_no_percentiles_at_all(self) -> None:
        # Four passing samples: the block itself emits (vector + triple),
        # but even the median needs five contributing samples.
        block = latency_block(tuple(sample(ms) for ms in (10, 20, 30, 40)))
        assert block is not None
        assert block.percentiles == ()
        assert block.sorted_passing_latencies_ms == (10, 20, 30, 40)

    def test_five_passing_samples_support_the_median_only(self) -> None:
        block = latency_block(tuple(sample(ms) for ms in (10, 20, 30, 40, 50)))
        assert block is not None
        assert block.percentiles == (("p50Ms", 30),)


def bar(*bounds: LatencyBound) -> LatencyBar:
    return LatencyBar(bounds=bounds)


def derived_bar(*labels: str, baseline: tuple[int, ...], samples: int) -> LatencyBar:
    return LatencyBar(
        bounds=tuple(LatencyBound(label) for label in labels),
        origin=ThresholdSource.BASELINE_DERIVED,
        baseline=LatencyBaseline(baseline, samples),
    )


class TestExplicitRequirements:
    """An explicit ceiling is decided by latency/compliance-exact-binomial on
    the count of successful latencies within it."""

    def test_compliance_is_demonstrated_by_the_count_within(self) -> None:
        # p50 <= 30 over 5 latencies at alpha 0.05: y_min is 5 (1/32 <= 0.05),
        # and only 3 are within — though the raw median (30) meets the ceiling.
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 30)), [10, 20, 30, 40, 50], 5, Intent.VERIFICATION
        )
        outcome = evaluation.evaluations[0]
        compliance = outcome.judgement.compliance
        assert compliance is not None
        assert (compliance.within_threshold, compliance.minimum_within) == (3, 5)
        assert compliance.advisory_percentile_pass is True
        assert outcome.verdict is Verdict.FAIL
        assert outcome.judgement.rule == "latency/compliance-exact-binomial"

    def test_every_latency_within_passes(self) -> None:
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 50)), [10, 20, 30, 40, 50], 5, Intent.VERIFICATION
        )
        assert evaluation.verdict is Verdict.PASS

    def test_too_few_successful_latencies_is_inconclusive_not_a_judgement(self) -> None:
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 100)), [10, 20], 8, Intent.VERIFICATION
        )
        compliance = evaluation.evaluations[0].judgement.compliance
        assert compliance is not None and not compliance.pass_possible
        assert evaluation.verdict is Verdict.INCONCLUSIVE

    def test_a_breach_outranks_an_inconclusive_sibling(self) -> None:
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 1), LatencyBound("p95", 1000)),
            [10, 20, 30, 40, 50],
            5,
            Intent.VERIFICATION,
        )
        verdicts = {e.bound.percentile: e.verdict for e in evaluation.evaluations}
        assert verdicts == {"p50": Verdict.FAIL, "p95": Verdict.INCONCLUSIVE}
        assert evaluation.verdict is Verdict.FAIL

    def test_observed_percentiles_are_gated_descriptive_context(self) -> None:
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 100)), list(range(1, 13)), 12, Intent.VERIFICATION
        )
        assert [label for label, _ in evaluation.observed] == ["p50", "p90"]


class TestBaselineDerived:
    """A baseline-derived constraint is decided by latency/precedence after the
    run, for the number of successful latencies the run actually returned."""

    def test_threshold_is_derived_for_the_actual_count(self) -> None:
        latency_bar = derived_bar("p50", baseline=tuple(range(1, 201)), samples=200)
        evaluation = evaluate_latency(latency_bar, list(range(1, 51)), 50, Intent.VERIFICATION)
        judgement = evaluation.evaluations[0].judgement
        assert judgement.precedence is not None and judgement.precedence.rank is not None
        # Baseline latency k is k here, so the threshold is the rank itself.
        assert judgement.threshold_ms == judgement.precedence.rank
        assert evaluation.verdict is Verdict.PASS

    def test_saturated_is_inconclusive(self) -> None:
        # A p90 test of 10 against 32 baseline latencies: no rank achieves 0.05.
        latency_bar = derived_bar("p90", baseline=tuple(range(1, 33)), samples=32)
        evaluation = evaluate_latency(latency_bar, list(range(1, 11)), 10, Intent.VERIFICATION)
        judgement = evaluation.evaluations[0].judgement
        assert judgement.precedence is not None and judgement.precedence.saturated
        assert evaluation.verdict is Verdict.INCONCLUSIVE

    def test_degenerate_percentile_is_inconclusive_under_verification(self) -> None:
        latency_bar = derived_bar("p95", baseline=tuple(range(1, 1001)), samples=1000)
        evaluation = evaluate_latency(latency_bar, list(range(1, 16)), 15, Intent.VERIFICATION)
        assert evaluation.verdict is Verdict.INCONCLUSIVE

    def test_planning_warns_before_the_run_without_refusing(self) -> None:
        latency_bar = derived_bar("p99", baseline=tuple(range(1, 401)), samples=500)
        (planning,) = plan_latency(latency_bar, 200)
        assert planning.warns
        assert planning.precedence.expected_test_samples == 160
        assert plan_latency(bar(LatencyBound("p99", 500)), 200) == ()


class TestThroughTheEngine:
    def test_two_dimensional_verdict_through_the_engine(self) -> None:
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=bar(LatencyBound("p50", 60_000)),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("a",), kind=RunKind.TEST))
        assert result.latency is not None
        assert result.latency.contributing_samples == 10
        assert result.latency.verdict is Verdict.PASS
        assert result.composite is Verdict.PASS
        assert result.overall is not None and result.overall.latency_verdict is Verdict.PASS

    def test_inconclusive_latency_makes_the_test_inconclusive(self) -> None:
        # Every sample succeeds and the functional criterion passes, but no
        # count of 5 latencies can demonstrate a p50 requirement at alpha
        # 0.03 (1/32 > 0.03): the latency dimension, and the test, are
        # INCONCLUSIVE — decided on the actual count, so smoke runs it.
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=LatencyBar(bounds=(LatencyBound("p50", 60_000),), confidence=0.97),
        )
        result = execute(
            contract, RunPlan(samples=5, inputs=("a",), kind=RunKind.TEST, intent=Intent.SMOKE)
        )
        assert result.latency is not None
        assert result.latency.verdict is Verdict.INCONCLUSIVE
        assert result.composite is Verdict.INCONCLUSIVE
        assert result.overall is not None
        assert [t.id for t in result.overall.triggering] == ["latency p50"]
