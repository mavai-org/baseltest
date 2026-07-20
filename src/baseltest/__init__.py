"""baseltest: probabilistic testing for stochastic services.

Python-native counterpart to punit (Java) and feotest (Rust) in the
mavai framework family — statistical inference over repeated samples,
not a single pass/fail assertion.
"""

from importlib import metadata

__version__ = metadata.version("baseltest")
