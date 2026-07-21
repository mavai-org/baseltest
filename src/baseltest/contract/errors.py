"""The baseltest exception family: the base every domain error shares.

Anticipated, on-purpose failures — a rejected contract, an infeasible run, a
provider that did not deliver, a transform that could not parse — derive from
:class:`BaseltestError`, so a caller can catch the whole family with a single
``except``. Genuine defects (a bug in the testing machinery) deliberately do
*not* derive from it: they travel on their own exception types, so ``except
BaseltestError`` can never silently swallow a bug.
"""


class BaseltestError(Exception):
    """Base of every anticipated error baseltest raises on purpose."""


class PreconditionError(BaseltestError):
    """A public routine's precondition was violated at the trust boundary."""


class ContractValidationError(BaseltestError):
    """A declared contract failed validation at the trust boundary."""
