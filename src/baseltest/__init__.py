"""baseltest: probabilistic testing for stochastic services.

Python-native counterpart to punit (Java) and feotest (Rust) in the
mavai framework family — statistical inference over repeated samples,
not a single pass/fail assertion.

The common entry points are re-exported here: construct a :class:`Bindings`,
then call :func:`run`, :func:`explore`, :func:`optimize`, or
:func:`check_contract` on a contract file. These are the declarative
authoring surface (:mod:`baseltest.declarative`), promoted to the package
root for convenience; that module also carries the narrower stepper/scorer
context types, and :mod:`baseltest.contract` is the surface for authoring a
service contract in Python directly.
"""

from baseltest._version import __version__
from baseltest.contract import FileInput
from baseltest.declarative import (
    Bindings,
    check_contract,
    explore,
    optimize,
    run,
)

__all__ = [
    "Bindings",
    "FileInput",
    "__version__",
    "check_contract",
    "explore",
    "optimize",
    "run",
]
