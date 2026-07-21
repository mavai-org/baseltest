"""Shared numeric constants for the statistics primitives.

Kept in one place so every module in this package derives alpha from
confidence rather than hard-coding both, and so the soundness floor is
defined exactly once.
"""

DEFAULT_CONFIDENCE_LEVEL = 0.95
"""Confidence level used when a caller does not specify one explicitly."""

DEFAULT_POWER = 0.80
"""Detection power targeted when a caller does not specify one explicitly —
the probability a degradation worth catching is caught."""

SOUNDNESS_FLOOR_CONFIDENCE = 0.80
"""Minimum confidence level below which a test configuration is considered
statistically unsound. This is a fixed framework judgment, not a value
callers are expected to override.
"""
