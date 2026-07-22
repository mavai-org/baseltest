"""Risk-driven run sizing for the ``test`` verb: claims in, sample count out.

The operator declares how much genuine degradation they will tolerate and
how sure they want to be; the run's sample count is computed from those
claims against each empirical criterion's measured baseline. Claims come
from three places, in precedence order: a ``--tolerate`` flag, the
criterion's ``tolerate:`` contract key, and — on an interactive terminal —
a plain-language prompt. A non-interactive run with unclaimed empirical
criteria is refused before any invocation.

An explicit ``--samples`` stays available but never silent: the run is
priced in plain language (its acceptance floor and the drop it can
actually catch), and a weak design requires an explicit confirmation.
A tolerance at or above the proven baseline is pushed back on in the
other direction: the honest remedy is re-measuring, not asserting
improvement through the tolerance dial.

This package is a thin facade over the concern-split submodules: the value
model (`_model`), rate helpers (`_rates`), flag parsing (`_flags`), baseline
and criterion selection (`_criteria`), claim pricing (`_pricing`), the
disclosure renderers (`_render`), the interactive prompts (`_prompts`), the
three modes (`_modes`), and the `resolve_test_sizing` orchestrator
(`_resolve`).
"""

from ._model import ResolvedSizing, SizingClaim, SizingRefusalError
from ._resolve import resolve_test_sizing

__all__ = [
    "ResolvedSizing",
    "SizingClaim",
    "SizingRefusalError",
    "resolve_test_sizing",
]
