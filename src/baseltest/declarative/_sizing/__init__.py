"""Risk-driven run sizing for the ``test`` verb: claims in, sample count out.

The operator declares, per empirical criterion, the design alternative rate
— the degraded pass rate the test must catch reliably — and how rarely it
may raise a false alarm; the run's sample count is computed by resolved
sizing against each criterion's measured baseline (``regression/fisher``,
the cutoff fixed by the observed count; companion §5.4.1). The rate is not a
tolerance: the test still flags any degradation from the baseline. Claims
come from three places, in precedence order: a ``--tolerate`` flag, the
criterion's ``tolerate:`` contract key, and — on an interactive terminal —
a plain-language prompt. A non-interactive run with unclaimed empirical
criteria is refused before any invocation, as is a baseline too small for
any admissible test to reach and hold the target (``BASELINE_TOO_SMALL``).

An explicit ``--samples`` stays available but never silent: the run is
priced in plain language (its cutoff and the drop it can actually catch),
and a weak design requires an explicit confirmation. A rate at or above the
baseline (``ALTERNATIVE_NOT_BELOW_BASELINE``) is pushed back on in the other
direction: the honest remedy is re-measuring.

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
