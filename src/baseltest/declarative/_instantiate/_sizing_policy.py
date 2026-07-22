"""Run sizing: the N a run uses and where the number came from.

Sample sizing is decided at invocation, never in the file: the contract
carries the claim, the invocation carries the budget.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from baseltest.contract import Criterion
from baseltest.engine import Intent, RunKind
from baseltest.statistics import check_feasibility

from .._errors import ContractConfigurationError

DEFAULT_SAMPLES = 5
SILENT_DERIVATION_LIMIT = 100
RECOMMENDED_BASELINE_SAMPLES = 1000


@dataclass(frozen=True, slots=True)
class RunSizing:
    """A run's N and where the value came from — the run-plan line's data.

    Attributes:
        samples: The run's N (per configuration, for an explore run).
        provenance: ``"explicit"`` (a flag or API argument), ``"derived"``
            (the minimum the declared thresholds require), or
            ``"default"`` (the verb's fixed default).
        demanded_by: For a derived N, the criterion whose threshold set it.
        threshold: For a derived N, that criterion's threshold.
    """

    samples: int
    provenance: str
    demanded_by: str | None = None
    threshold: float | None = None


def _resolve_run_size(
    mode: RunKind,
    intent: Intent,
    samples: int | None,
    judged: Sequence[Criterion],
    samples_provenance: str | None = None,
) -> RunSizing:
    """The run's N: an explicit flag, or the verb's own sizing story.

    A test under validation intent derives its N from the claim — the
    largest per-criterion feasibility minimum — refusing a silently
    derived N above the limit (the gate binds the number nobody typed;
    an explicit flag of any size sails through; a risk-driven N computed
    from the operator's declared tolerance arrives with its own
    provenance). A smoke test gets the small fixed default. A measure
    gets no default at all: its budget is an experimental-design decision
    and must be typed.
    """
    if samples is not None:
        return RunSizing(samples=samples, provenance=samples_provenance or "explicit")
    if mode is RunKind.MEASURE:
        raise ContractConfigurationError(
            "a measure run's sample count is yours to choose — run with "
            f"`--samples N` ({RECOMMENDED_BASELINE_SAMPLES} is a solid "
            "baseline-grade count; a smaller deliberate budget is legitimate, "
            "and an empirical bar derived from a smaller baseline simply "
            "widens honestly)"
        )
    anchors = [
        (check_feasibility(1, c.threshold, c.confidence).minimum_samples, c)
        for c in judged
        if c.threshold is not None
    ]
    if intent is Intent.VERIFICATION and anchors:
        minimum, criterion = max(anchors, key=lambda pair: pair[0])
        if minimum > SILENT_DERIVATION_LIMIT:
            raise ContractConfigurationError(
                f"criterion {criterion.name} (threshold {criterion.threshold}) "
                f"needs at least {minimum} samples — more than the "
                f"{SILENT_DERIVATION_LIMIT} this framework will derive silently. "
                f"Run it deliberately with `--samples {minimum}`, or declare "
                "`intent: smoke` for a cheap pass that renders no statistical "
                "verdict"
            )
        return RunSizing(
            samples=minimum,
            provenance="derived",
            demanded_by=criterion.name,
            threshold=criterion.threshold,
        )
    return RunSizing(samples=DEFAULT_SAMPLES, provenance="default")
