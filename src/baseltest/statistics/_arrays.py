"""Array type names for the statistics core.

numpy is treated as untyped at this project's mypy target (its inline stubs
need Python 3.12 syntax), so these aliases document what an array holds and
type as ``Any``.
"""

from typing import Any, TypeAlias

IntArray: TypeAlias = Any
"""A numpy array of integers (counts, cutoffs, sizes)."""

FloatArray: TypeAlias = Any
"""A numpy array of floating-point probabilities."""

BoolArray: TypeAlias = Any
"""A numpy array of booleans."""
