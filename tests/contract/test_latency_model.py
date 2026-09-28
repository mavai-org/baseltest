"""The latency bar: resolved bounds, validated at construction."""

import pytest

from baseltest.contract import LatencyBar, LatencyBaseline, LatencyBound
from baseltest.statistics import ThresholdSource


class TestLatencyBound:
    def test_rejects_unknown_percentile(self) -> None:
        with pytest.raises(ValueError, match="unknown percentile"):
            LatencyBound(percentile="p97", threshold_ms=100)

    def test_rejects_non_positive_threshold(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            LatencyBound(percentile="p95", threshold_ms=0)

    def test_a_baseline_derived_bound_has_no_ceiling_until_the_run(self) -> None:
        assert LatencyBound(percentile="p95").threshold_ms is None
        assert LatencyBound(percentile="p95").level == 0.95


class TestLatencyBar:
    def test_rejects_empty_bounds(self) -> None:
        with pytest.raises(ValueError, match="at least one bound"):
            LatencyBar(bounds=())

    def test_rejects_unknown_origin(self) -> None:
        with pytest.raises(ValueError, match="ThresholdSource"):
            LatencyBar(
                bounds=(LatencyBound("p50", 100),),
                origin="advisory",  # type: ignore[arg-type]
            )

    def test_baseline_derived_bar_carries_its_baseline_and_no_ceilings(self) -> None:
        baseline = LatencyBaseline((10, 20, 30), samples=4)
        source = ThresholdSource.BASELINE_DERIVED
        derived = LatencyBar(bounds=(LatencyBound("p50"),), origin=source, baseline=baseline)
        assert derived.baseline is not None and derived.baseline.passing_rate == 0.75
        with pytest.raises(ValueError, match="carries its baseline"):
            LatencyBar(bounds=(LatencyBound("p50"),), origin=source)
        with pytest.raises(ValueError, match="after the run"):
            LatencyBar(bounds=(LatencyBound("p50", 100),), origin=source, baseline=baseline)

    def test_latency_baseline_is_sorted_and_no_larger_than_its_sampling(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            LatencyBaseline((30, 10), samples=2)
        with pytest.raises(ValueError, match="more latencies than samples"):
            LatencyBaseline((10, 20, 30), samples=2)

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
