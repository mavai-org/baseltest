"""The registry: named bindings, checks, and transforms, resolved at load time.

A :class:`Registry` is a caller-held object. Bindings, checks, and transforms
register onto an instance — ``@registry.binding(...)``, ``@registry.check(...)``,
``@registry.transform(...)`` — and a run threads that instance through
resolution. ``@binding`` and ``@binding_factory`` register **service types**
(user entries in the same registry the built-in ``language-model`` type lives
in); ``@check`` and ``@transform`` register the named predicates and
transformations criteria reference. Two registries are fully independent: two
contracts with different registrations run in one process without cross-talk,
and a test constructs a fresh registry rather than resetting a global.

This package is a thin facade over the concern-split submodules: the
registration guards (`_guards`), the transform registration record and its
schema loading (`_transform`), the user service-type construction
(`_service_types`), and the `Registry` class itself (`_core`).
"""

from ._core import Registry
from ._guards import RESERVED_COVARIATE_KEYS
from ._transform import _STOCK_TRANSFORMS as _STOCK_TRANSFORMS
from ._transform import TransformRegistration

__all__ = [
    "RESERVED_COVARIATE_KEYS",
    "Registry",
    "TransformRegistration",
]
