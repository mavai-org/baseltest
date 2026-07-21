"""Shared input preconditions for the statistics boundary.

The statistics package is an independently-scrutable, directly-tested public
surface, so its public routines validate their inputs at that boundary — a
violated precondition is a caller's defect and is refused immediately rather
than silently producing a meaningless number. These checks live here once,
rather than duplicated across the modules that share them.
"""

import math


def validate_counts(successes: int, trials: int) -> None:
    """Refuse a non-positive trial count or a success count out of range."""
    if trials <= 0:
        raise ValueError("trials must be a positive integer")
    if successes < 0:
        raise ValueError("successes must be non-negative")
    if successes > trials:
        raise ValueError("successes cannot exceed trials")


def validate_confidence_level(confidence_level: float) -> None:
    """Refuse a confidence level that is not strictly inside (0, 1)."""
    if math.isnan(confidence_level) or not (0.0 < confidence_level < 1.0):
        raise ValueError("confidence_level must be strictly between 0 and 1")


def validate_unit_interval(name: str, value: float) -> None:
    """Refuse a named value that is not strictly inside (0, 1)."""
    if math.isnan(value) or not (0.0 < value < 1.0):
        raise ValueError(f"{name} must be strictly between 0 and 1")
