"""Edge-case tests for design and resolved sizing under regression/fisher."""

from baseltest.statistics import (
    SizingRefusal,
    check_sizing_domain,
    resolved_detectable_rate,
    resolved_power,
    resolved_sizing,
)


def test_domain_refusals_in_order_of_precedence() -> None:
    assert check_sizing_domain(0.0, 100, 0.5, 200) is SizingRefusal.ZERO_BASELINE
    assert check_sizing_domain(0.9, 100, 0.9, 200) is SizingRefusal.ALTERNATIVE_NOT_BELOW_BASELINE
    assert check_sizing_domain(0.9, 100, 0.8, 200) is SizingRefusal.TEST_LARGER_THAN_BASELINE
    assert check_sizing_domain(0.9, 100, 0.8, 100) is None


def test_resolved_sizing_stays_at_the_target_rather_than_first_crossing() -> None:
    sizing = resolved_sizing(951, 1000, 0.925, 0.05, 0.80)
    assert sizing is not None
    assert (sizing.required_samples, sizing.first_crossing) == (966, 868)
    assert sizing.power >= 0.80


def test_resolved_sizing_refuses_a_baseline_too_small() -> None:
    assert resolved_sizing(288, 300, 0.93, 0.05, 0.80) is None


def test_resolved_power_rises_with_the_size_of_the_drop() -> None:
    powers = [resolved_power(951, 1000, 400, 0.05, rate) for rate in (0.94, 0.92, 0.90)]
    assert powers == sorted(powers)


def test_resolved_detectable_rate_inverts_the_resolved_power() -> None:
    rate = resolved_detectable_rate(951, 1000, 400, 0.05, 0.80)
    assert rate is not None
    assert resolved_power(951, 1000, 400, 0.05, rate) >= 0.80
    assert resolved_power(951, 1000, 400, 0.05, rate + 1e-6) < 0.80


def test_nothing_is_detectable_against_a_zero_cutoff() -> None:
    assert resolved_detectable_rate(0, 100, 50, 0.05, 0.80) is None
