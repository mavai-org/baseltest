"""Edge-case and validation tests for feasibility checking."""

import pytest

from baseltest.statistics import check_feasibility


def test_large_sample_size_is_always_feasible() -> None:
    result = check_feasibility(sample_size=1_000_000, target_proportion=0.9, confidence_level=0.95)
    assert result.feasible


def test_single_sample_is_infeasible_for_a_meaningful_target() -> None:
    result = check_feasibility(sample_size=1, target_proportion=0.9, confidence_level=0.95)
    assert not result.feasible


def test_zero_target_is_trivially_feasible() -> None:
    result = check_feasibility(sample_size=5, target_proportion=0.0, confidence_level=0.95)
    assert result.feasible
    assert result.minimum_samples == 0


def test_target_close_to_one_needs_a_large_sample_size() -> None:
    result = check_feasibility(sample_size=100, target_proportion=0.999, confidence_level=0.95)
    assert not result.feasible
    assert result.minimum_samples > 100


def test_undersized_configuration_reports_both_component_checks() -> None:
    result = check_feasibility(sample_size=5, target_proportion=0.9, confidence_level=0.95)
    assert result.feasible is (result.meets_confidence_floor and result.sample_size_adequate)


def test_confidence_below_soundness_floor_is_infeasible_even_with_ample_samples() -> None:
    result = check_feasibility(sample_size=1_000_000, target_proportion=0.5, confidence_level=0.5)
    assert not result.meets_confidence_floor
    assert not result.feasible


def test_rejects_non_positive_sample_size() -> None:
    with pytest.raises(ValueError):
        check_feasibility(sample_size=0, target_proportion=0.9, confidence_level=0.95)


@pytest.mark.parametrize("target_proportion", [-0.1, 1.0, 1.1])
def test_rejects_target_outside_unit_interval(target_proportion: float) -> None:
    with pytest.raises(ValueError):
        check_feasibility(
            sample_size=10, target_proportion=target_proportion, confidence_level=0.95
        )


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.1, 1.1])
def test_rejects_confidence_outside_open_unit_interval(confidence_level: float) -> None:
    with pytest.raises(ValueError):
        check_feasibility(sample_size=10, target_proportion=0.9, confidence_level=confidence_level)
