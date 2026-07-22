"""Descriptive proportion statistics: variance and standard error."""

import math

from baseltest.statistics import proportion_standard_error, proportion_variance


class TestProportionVariance:
    def test_variance_is_p_times_one_minus_p(self) -> None:
        assert proportion_variance(4, 5) == 0.8 * (1 - 0.8)

    def test_variance_zero_at_the_extremes(self) -> None:
        assert proportion_variance(0, 5) == 0.0
        assert proportion_variance(5, 5) == 0.0

    def test_variance_zero_for_empty_tally(self) -> None:
        assert proportion_variance(0, 0) == 0.0


class TestProportionStandardError:
    def test_standard_error_is_sqrt_variance_over_n(self) -> None:
        assert proportion_standard_error(4, 5) == math.sqrt(0.8 * (1 - 0.8) / 5)

    def test_standard_error_zero_at_the_extremes(self) -> None:
        assert proportion_standard_error(0, 5) == 0.0
        assert proportion_standard_error(5, 5) == 0.0

    def test_standard_error_zero_for_empty_tally(self) -> None:
        assert proportion_standard_error(0, 0) == 0.0
