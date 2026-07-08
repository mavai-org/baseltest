"""The shared latency summary: passing-samples basis, gating, sorted vector."""

from baseltest.engine import SampleRecord, latency_block


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

    def test_single_passing_sample_supports_p50_only(self) -> None:
        block = latency_block((sample(42),))
        assert block is not None
        assert block.percentiles == (("p50Ms", 42),)
        assert block.sorted_passing_latencies_ms == (42,)
