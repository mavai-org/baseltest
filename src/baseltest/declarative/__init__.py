"""Declarative authoring: run a mavai contract file against your service.

This package is the reader for the family's contract-file format
(``mavai-contract/1``): it parses and validates a contract file, instantiates the
service contract it describes, and runs it through the same engine a
hand-authored contract uses.

Its public Python surface is deliberately tiny — three registration
decorators and one entry point:

- :func:`binding` registers the code that invokes your service by name,
  optionally declaring the covariates that make up its computed identity.
- :func:`binding_factory` registers a configurable service type: a factory
  whose signature is the configuration schema, constructing the per-sample
  callable from one services-file grid point.
- :func:`check` registers a named predicate for the ``satisfies:`` form.
- :func:`transform` registers a named transformation for the ``transform:``
  key.
- :func:`run` loads and executes a contract file (test or measure).
- :func:`explore` runs a contract over every configuration in its
  service's grid, one descriptive artefact per configuration.
- :func:`check_contract` validates every load-time join — contract,
  services file, bindings — with zero samples: the authoring loop's
  compile step (the ``basel check`` verb).

Everything else in this package is private implementation; import nothing
from its underscore modules. Graduating out of the declarative surface
means authoring the contract directly (``baseltest.contract``) — at that
point nothing here is needed any more.
"""

from ._registry import binding, binding_factory, check, transform
from ._runner import check as check_contract
from ._runner import explore, run

__all__ = [
    "binding",
    "binding_factory",
    "check",
    "check_contract",
    "explore",
    "run",
    "transform",
]
