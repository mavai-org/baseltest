"""Instantiation: a validated contract declaration into a live service contract and plan.

The run mode is supplied by the invocation (the verb), never by the file:
``test`` instantiates a probabilistic test over the thresholded criteria
(criteria without a bar are skipped, reported by name — never silently);
``measure`` instantiates a measure experiment over every criterion.

This package is a thin facade over the concern-split submodules:
``_compose`` (the ``test``/``measure`` composition and its
:class:`Instantiation` result), ``_explore`` and ``_optimize_point`` (the
other verbs), and the shared building blocks ``_views``,
``_postconditions``, ``_service``, ``_sizing_policy``, ``_latency``, and
``_baseline``.
"""

from ._baseline import BaselineContext
from ._compose import Instantiation, instantiate
from ._explore import ExploreConfiguration, instantiate_explore
from ._optimize_point import OptimizePoint, instantiate_optimize_point, optimize_definition
from ._sizing_policy import RunSizing
from ._views import descriptive_view_fingerprints

__all__ = [
    "BaselineContext",
    "ExploreConfiguration",
    "Instantiation",
    "OptimizePoint",
    "RunSizing",
    "descriptive_view_fingerprints",
    "instantiate",
    "instantiate_explore",
    "instantiate_optimize_point",
    "optimize_definition",
]
