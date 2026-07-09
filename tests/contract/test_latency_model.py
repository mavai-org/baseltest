"""The latency bar: resolved bounds, validated at construction."""

import pytest

from baseltest.contract import LatencyBar, LatencyBound


class TestLatencyBound:
    def test_rejects_unknown_percentile(self) -> None:
        with pytest.raises(ValueError, match="unknown percentile"):
            LatencyBound(percentile="p97", threshold_ms=100)

    def test_rejects_non_positive_threshold(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            LatencyBound(percentile="p95", threshold_ms=0)

    def test_carries_derivation_facts_for_baseline_derived_bounds(self) -> None:
        bound = LatencyBound(
            percentile="p95",
            threshold_ms=420,
            rank=196,
            baseline_percentile_ms=356,
            baseline_samples=200,
        )
        assert (bound.rank, bound.baseline_samples) == (196, 200)


class TestLatencyBar:
    def test_rejects_empty_bounds(self) -> None:
        with pytest.raises(ValueError, match="at least one bound"):
            LatencyBar(bounds=())

    def test_rejects_unknown_origin(self) -> None:
        with pytest.raises(ValueError, match="origin"):
            LatencyBar(bounds=(LatencyBound("p50", 100),), origin="advisory")

    def test_rejects_duplicate_percentiles(self) -> None:
        with pytest.raises(ValueError, match="at most once"):
            LatencyBar(bounds=(LatencyBound("p50", 100), LatencyBound("p50", 200)))

    def test_rejects_out_of_order_bounds(self) -> None:
        with pytest.raises(ValueError, match="percentile order"):
            LatencyBar(bounds=(LatencyBound("p95", 200), LatencyBound("p50", 100)))

    def test_rejects_decreasing_thresholds(self) -> None:
        with pytest.raises(ValueError, match="non-decreasing"):
            LatencyBar(bounds=(LatencyBound("p50", 500), LatencyBound("p95", 100)))

    def test_accepts_a_well_formed_bar(self) -> None:
        bar = LatencyBar(
            bounds=(LatencyBound("p50", 100), LatencyBound("p95", 500)),
            origin="explicit",
            confidence=0.95,
        )
        assert [b.percentile for b in bar.bounds] == ["p50", "p95"]
