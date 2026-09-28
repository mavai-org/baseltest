"""Shared numeric constants for the statistics primitives.

Kept in one place so every default a caller does not state is defined
exactly once.
"""

DEFAULT_CONFIDENCE_LEVEL = 0.95
"""Confidence level used when a caller does not specify one explicitly."""

DEFAULT_POWER = 0.80
"""Detection power targeted when a caller does not specify one explicitly —
the probability a degradation worth catching is caught."""
