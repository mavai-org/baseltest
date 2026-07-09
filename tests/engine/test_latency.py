"""The shared latency summary: passing-samples basis, gating, sorted vector."""

from baseltest.contract import Criterion, LatencyBar, LatencyBound, ServiceContract, contains
from baseltest.engine import (
    RunKind,
    RunPlan,
    SampleRecord,
    Verdict,
    evaluate_latency,
    execute,
    latency_block,
)


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


def bar(*bounds: LatencyBound, origin: str = "explicit") -> LatencyBar:
    return LatencyBar(bounds=bounds, origin=origin)


class TestEvaluateLatency:
    def test_one_sided_upper_equality_passes(self) -> None:
        evaluation = evaluate_latency(bar(LatencyBound("p50", 30)), [10, 20, 30, 40, 50], 5)
        assert evaluation.evaluations[0].observed_ms == 30
        assert evaluation.evaluations[0].status == "pass"
        assert evaluation.verdict is Verdict.PASS

    def test_breach_fails_the_dimension(self) -> None:
        evaluation = evaluate_latency(bar(LatencyBound("p50", 29)), [10, 20, 30, 40, 50], 5)
        assert evaluation.evaluations[0].status == "fail"
        assert evaluation.verdict is Verdict.FAIL

    def test_too_few_passing_samples_is_infeasible_not_a_judgement(self) -> None:
        evaluation = evaluate_latency(bar(LatencyBound("p50", 100)), [10, 20], 8)
        outcome = evaluation.evaluations[0]
        assert outcome.status == "infeasible"
        assert outcome.observed_ms is None
        assert outcome.reason is not None and "at least 5 passing samples" in outcome.reason
        assert evaluation.verdict is Verdict.INCONCLUSIVE

    def test_a_breach_outranks_an_infeasible_sibling(self) -> None:
        evaluation = evaluate_latency(
            bar(LatencyBound("p50", 1), LatencyBound("p95", 1000)),
            [10, 20, 30, 40, 50],
            5,
        )
        statuses = {e.bound.percentile: e.status for e in evaluation.evaluations}
        assert statuses == {"p50": "fail", "p95": "infeasible"}
        assert evaluation.verdict is Verdict.FAIL

    def test_observed_percentiles_are_gated_descriptive_context(self) -> None:
        evaluation = evaluate_latency(bar(LatencyBound("p50", 100)), list(range(1, 13)), 12)
        assert [label for label, _ in evaluation.observed] == ["p50", "p90"]

    def test_two_dimensional_composite_through_the_engine(self) -> None:
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

    def test_infeasible_latency_makes_the_composite_inconclusive(self) -> None:
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=bar(LatencyBound("p50", 60_000)),
        )
        # 4 samples: the functional criterion passes, but the median needs
        # 5 passing samples — no latency judgement, so no composite pass.
        result = execute(contract, RunPlan(samples=4, inputs=("a",), kind=RunKind.TEST))
        assert result.latency is not None
        assert result.latency.verdict is Verdict.INCONCLUSIVE
        assert result.composite is Verdict.INCONCLUSIVE
