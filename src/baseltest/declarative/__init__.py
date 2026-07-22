"""Declarative authoring: run a mavai contract file against your service.

This package is the reader for the family's contract-file format
(``mavai-contract/1``): it parses and validates a contract file, instantiates the
service contract it describes, and runs it through the same engine a
hand-authored contract uses.

Its public Python surface is deliberately tiny — a caller-held registry
and a handful of entry points:

- :class:`Registry` is the object bindings, checks, and transforms register
  onto (``@registry.binding(...)``, ``@registry.check(...)``,
  ``@registry.transform(...)``), and a run threads through resolution. Two
  registries are fully independent — two contracts with different
  registrations run in one process without cross-talk. A
  ``mavai-bindings.py`` file binds one as ``registry``; an API caller
  constructs one and passes ``registry=`` to the entry points.
- :func:`stepper` registers a stepper factory for the ``optimizations:``
  section's ``stepper:`` key; :func:`scorer` registers a scorer for its
  ``scorer:`` key.
- :func:`run` loads and executes a contract file (test or measure).
- :func:`explore` runs a contract over every configuration in its
  service's grid, one descriptive artefact per configuration.
- :func:`optimize` runs a contract's declared Optimize experiments:
  iterative configuration search, one full-history artefact per run.
- :func:`check_contract` validates every load-time join — contract,
  services file, bindings — with zero samples: the authoring loop's
  compile step (the ``basel check`` verb).

Stepper and scorer authors also consume the context types:
:class:`OptimizeContext`, :class:`IterationResult`,
:class:`IterationSummary`, :class:`FailureDetail`,
:class:`FailureExemplar`, and :class:`LatencySummary`.

Everything else in this package is private implementation; import nothing
from its underscore modules. Graduating out of the declarative surface
means authoring the contract directly (``baseltest.contract``) — at that
point nothing here is needed any more.
"""

from ._registry import Registry
from ._runner import check as check_contract
from ._runner import explore, optimize, run
from ._steppers import (
    FailureDetail,
    FailureExemplar,
    IterationResult,
    IterationSummary,
    LatencySummary,
    OptimizeContext,
    scorer,
    stepper,
)

__all__ = [
    "FailureDetail",
    "FailureExemplar",
    "IterationResult",
    "IterationSummary",
    "LatencySummary",
    "OptimizeContext",
    "Registry",
    "check_contract",
    "explore",
    "optimize",
    "run",
    "scorer",
    "stepper",
]
