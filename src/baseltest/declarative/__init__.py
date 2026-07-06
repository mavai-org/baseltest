"""Declarative authoring: run a mavai task file against your service.

This package is the reader for the family's task-file format
(``mavai-task/1``): it parses and validates a task file, instantiates the
service contract it describes, and runs it through the same engine a
hand-authored contract uses.

Its public Python surface is deliberately tiny — three registration
decorators and one entry point:

- :func:`binding` registers the code that invokes your service by name.
- :func:`check` registers a named predicate for the ``satisfies:`` form.
- :func:`transform` registers a named transformation for the ``transform:``
  key.
- :func:`run` loads and executes a task file.

Everything else in this package is private implementation; import nothing
from its underscore modules. Graduating out of the declarative surface
means authoring the contract directly (``baseltest.contract``) — at that
point nothing here is needed any more.
"""

from ._registry import binding, check, transform
from ._runner import run

__all__ = ["binding", "check", "run", "transform"]
