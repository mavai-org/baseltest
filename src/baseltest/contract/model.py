"""Core value types: the service contract, its criteria, and their metadata."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .postconditions import Postcondition


class TransformError(Exception):
    """An anticipated transformation failure: the response could not be turned
    into the value under judgement.

    Raised by a transform callable when the response does not parse or does
    not yield the expected value -- a malformed JSON body, an unexpected
    document shape. The evaluation counts it as a failed trial with a
    transform-failure reason; it never aborts a run. Any *other* exception
    escaping a transform is treated as a defect and propagates.
    """


@dataclass(frozen=True, slots=True)
class ThresholdProvenance:
    """Where a criterion's declared threshold comes from.

    Pure metadata for reporting and audit-facing exports; never affects
    evaluation.

    Attributes:
        origin: The category of source, e.g. ``"sla"``, ``"slo"``,
            ``"policy"``, or ``"unspecified"``.
        contract_ref: A document reference for the stipulation, e.g.
            ``"Payment Provider SLA v2.0 §4.1"``, when one was declared.
    """

    origin: str = "unspecified"
    contract_ref: str | None = None


@dataclass(frozen=True, slots=True)
class Criterion:
    """One criterion: a single Bernoulli stream with its own bar.

    A response passes the criterion iff every postcondition holds (a
    conjunction). When ``transform`` is set, the raw response is first
    turned into the value under judgement; a :class:`TransformError` from
    the transform is a failed trial, not an abort.

    Attributes:
        name: The criterion's stable identifier within its contract.
        postconditions: The checks, evaluated in declaration order.
        threshold: The declared minimum acceptable pass rate in ``(0, 1)``,
            or ``None`` for a criterion that is characterised, never judged.
        confidence: The confidence level for this criterion's verdict.
        transform: Optional callable turning the raw response into the value
            under judgement, made available to postconditions.
        provenance: Where the threshold comes from, when one is declared.
    """

    name: str
    postconditions: tuple[Postcondition, ...]
    threshold: float | None = None
    confidence: float = 0.95
    transform: Callable[[str], Any] | None = None
    provenance: ThresholdProvenance = field(default_factory=ThresholdProvenance)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("criterion name must be non-empty")
        if not self.postconditions:
            raise ValueError(f"criterion {self.name!r} declares no postconditions")
        if self.threshold is not None and not 0.0 < self.threshold < 1.0:
            raise ValueError(
                f"criterion {self.name!r}: threshold must be in (0, 1), got {self.threshold}"
            )
        if not 0.0 < self.confidence < 1.0:
            raise ValueError(
                f"criterion {self.name!r}: confidence must be in (0, 1), got {self.confidence}"
            )

    @property
    def is_thresholded(self) -> bool:
        """Whether this criterion declares a bar and therefore receives a verdict."""
        return self.threshold is not None


@dataclass(frozen=True, slots=True)
class ServiceContract:
    """A stochastic service under test: identity, invocation, and criteria.

    Attributes:
        contract_id: The contract's stable identifier; names run artefacts.
        invoke: The invocation callable -- accepts one input, returns one
            response. An anticipated bad response is *returned* (for the
            criteria to judge); only genuine defects raise, and a raising
            invocation aborts the run.
        criteria: One or more criteria, each judged independently over the
            same samples.
    """

    contract_id: str
    invoke: Callable[[str], str]
    criteria: tuple[Criterion, ...]

    def __post_init__(self) -> None:
        if not self.contract_id:
            raise ValueError("contract_id must be non-empty")
        if not self.criteria:
            raise ValueError(f"contract {self.contract_id!r} declares no criteria")
        names = [criterion.name for criterion in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError(f"contract {self.contract_id!r} has duplicate criterion names")

    @property
    def thresholded_criteria(self) -> tuple[Criterion, ...]:
        """The criteria that declare a threshold and therefore receive verdicts."""
        return tuple(c for c in self.criteria if c.is_thresholded)
