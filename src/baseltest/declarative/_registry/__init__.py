"""The registry: named bindings, checks, and transforms, resolved at load time.

:class:`Registry` is the **internal** resolution object — it holds the
registered service types, checks, transforms, steppers, and scorers, and
answers the name lookups a run makes. Authors never touch it: they register
onto a :class:`Bindings` (``@bindings.binding(...)``, ``@bindings.check(...)``,
``@bindings.transform(...)``, …), which owns a `Registry` and exposes only the
registration decorators; the loader threads that internal `Registry` through
the run. Two registries are fully independent: two contracts with different
registrations run in one process without cross-talk, and a test constructs a
fresh one rather than resetting a global.

This package is a thin facade over the concern-split submodules: the public
authoring facade (`_bindings`), the registration guards (`_guards`), the
transform registration record and its schema loading (`_transform`), the user
service-type construction (`_service_types`), and the internal `Registry`
class itself (`_core`).
"""

from ._bindings import Bindings
from ._core import Registry
from ._guards import RESERVED_COVARIATE_KEYS
from ._transform import _STOCK_TRANSFORMS as _STOCK_TRANSFORMS
from ._transform import TransformRegistration

__all__ = [
    "Bindings",
    "RESERVED_COVARIATE_KEYS",
    "Registry",
    "TransformRegistration",
]
