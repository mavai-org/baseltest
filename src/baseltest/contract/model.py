"""Core value types: the service contract, its criteria, and their metadata."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar

from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL

from .errors import BaseltestError
from .postconditions import Postcondition

_RequestContra = TypeVar("_RequestContra", contravariant=True)


class Service(Protocol[_RequestContra]):
    """The stochastic service under test: one request in, one response out.

    Structural, so an author's plain function or lambda ``(request) -> str``
    is a ``Service`` without inheriting anything. An anticipated bad response
    is *returned* for the criteria to judge; only a genuine defect raises,
    aborting the run.
    """

    def __call__(self, request: _RequestContra, /) -> str: ...


RequestT = TypeVar("RequestT")


class TransformError(BaseltestError):
    """An anticipated transformation failure: the response could not be turned
    into the value under judgement.

    Raised by a transform callable when the response does not parse or does
    not yield the expected value -- a malformed JSON body, an unexpected
    document shape. The evaluation counts it as a failed trial with a
    transform-failure reason; it never aborts a run. Any *other* exception
    escaping a transform is treated as a defect and propagates.
    """


class ServiceDeliveryError(BaseltestError):
    """An anticipated delivery failure: the service did not produce a response.

    Raised by an invocation when the service could not be reached or
    answered with a server-side error — a failed delivery, which is a
    *failed sample*: the engine counts it against every criterion with
    this failure's message as the reason, and the run completes to a
    verdict. An unreachable service is a failed service; hiding that
    behind an abort would leave the cause buried and the rate unjudged.

    Reserve other exceptions for genuine defects (misconfiguration, a bug
    in a binding) — those still abort the run.
    """


class MediaKind(StrEnum):
    """The declared content class of a file-sourced media input part.

    A closed set, named by the author (never sniffed) and parsed once at the
    contract boundary, so a wrong kind is unrepresentable downstream rather
    than a string checked in several places.
    """

    FILE = "file"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class FileInput:
    """A file-sourced input part, handed to a bound service verbatim.

    The typed reference the framework delivers for a media (or otherwise
    file-sourced) input part: the resolved ``path``, the declared ``kind``,
    the ``data`` bytes read once at load time, and their SHA-256
    ``content_hash``. A bound service opens or forwards it and calls whatever
    it likes -- an STT SDK, a cloud API -- and the framework never interprets
    the bytes.

    A *text* input part is deliberately not a ``FileInput``: it resolves to
    the decoded ``str``, so ``FileInput`` always carries opaque/binary
    content. Only the content (via ``content_hash``), never the path, feeds
    a baseline's inputs identity -- a file that drifts behind a stable path
    changes the identity, so a baseline cannot be silently reused over
    other bytes.
    """

    path: Path
    kind: MediaKind
    data: bytes = field(repr=False)
    content_hash: str

    def identity(self) -> dict[str, str]:
        """The canonical identity fragment folded into a baseline's inputs
        identity: content hash and kind, never the path."""
        return {"kind": self.kind, "sha256": self.content_hash}


@dataclass(frozen=True, slots=True)
class MessageParts:
    """An ordered multi-part input: text and media forming one message.

    The multimodal shape -- an instruction beside an image, a question beside
    a document. Each part is a text ``str`` or a :class:`FileInput`; part
    **order is significant** (it is the order the model receives them) and is
    preserved in the inputs identity, unlike the order-insensitive input list.
    A single-part input is not wrapped -- it stays a bare ``str`` or
    ``FileInput`` -- so this type only appears when an input genuinely mixes
    parts. Assembling the parts into a provider message is the language-model
    service's concern.
    """

    parts: tuple[str | FileInput, ...]


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
    conjunction). Each postcondition names the view it judges; the views
    themselves are declared on the contract and computed at most once per
    response, shared across criteria.

    Attributes:
        name: The criterion's stable identifier within its contract.
        postconditions: The checks, evaluated in declaration order.
        threshold: The declared minimum acceptable pass rate in ``(0, 1)``,
            or ``None`` for a criterion that is characterised, never judged.
        confidence: The confidence level for this criterion's verdict.
        cutoff: For a baseline-derived (regression) criterion, the resolved
            integer decision artefact: the verdict is PASS iff the raw
            observed success count meets it. The confidence correction
            already lives inside the derivation that produced the cutoff,
            so the observed count is compared directly. When ``None`` the
            threshold is a declared bar and the verdict is the test
            sample's own confidence bound clearing it (compliance posture).
        provenance: Where the threshold comes from, when one is declared.
    """

    name: str
    postconditions: tuple[Postcondition, ...]
    threshold: float | None = None
    confidence: float = DEFAULT_CONFIDENCE_LEVEL
    cutoff: int | None = None
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
        if self.cutoff is not None:
            if self.threshold is None:
                raise ValueError(
                    f"criterion {self.name!r}: a cutoff is the decision artefact of a "
                    "derived threshold; it cannot stand without one"
                )
            if self.cutoff < 1:
                raise ValueError(
                    f"criterion {self.name!r}: cutoff must be a positive count, got {self.cutoff}"
                )

    @property
    def is_thresholded(self) -> bool:
        """Whether this criterion declares a bar and therefore receives a verdict."""
        return self.threshold is not None

    def postconditions_for(self, input_index: int) -> tuple[Postcondition, ...]:
        """The postconditions a sample driven by this input is judged against.

        A criterion pools every input into one Bernoulli stream, so its
        ``postconditions`` tuple carries the checks for *all* inputs. A single
        sample is driven by one input and is judged against exactly the checks
        that apply to it — the always-on ones (``applies_to_input is None``)
        and the per-input expectation tagged with this input's index, in
        declaration order. The checks belonging to other inputs are not part
        of this trial at all: they neither run nor appear in its projection.
        """
        return tuple(
            postcondition
            for postcondition in self.postconditions
            if postcondition.applies_to_input is None
            or postcondition.applies_to_input == input_index
        )


# The supported percentile levels, in tail order. The latency dimension's
# vocabulary throughout the framework: bounds are declared, evaluated, and
# reported against these labels.
PERCENTILE_LEVELS: Mapping[str, float] = {"p50": 0.50, "p90": 0.90, "p95": 0.95, "p99": 0.99}


@dataclass(frozen=True, slots=True)
class LatencyBound:
    """One resolved upper bound on an observed latency percentile.

    A bound is always concrete by the time it reaches the contract: an
    explicit ceiling carries the declared milliseconds; a baseline-derived
    bound carries the order-statistic result and its derivation facts.

    Attributes:
        percentile: One of the supported labels (``p50``/``p90``/``p95``/``p99``).
        threshold_ms: The bound in milliseconds; the observed percentile
            passes iff it is at or below this value.
        rank: For a baseline-derived bound, the one-based order-statistic
            rank the threshold was read at.
        baseline_percentile_ms: For a baseline-derived bound, the
            baseline's nearest-rank point estimate — reporting context,
            never the threshold.
        baseline_samples: For a baseline-derived bound, the baseline's
            contributing-sample count.
    """

    percentile: str
    threshold_ms: int
    rank: int | None = None
    baseline_percentile_ms: int | None = None
    baseline_samples: int | None = None

    def __post_init__(self) -> None:
        if self.percentile not in PERCENTILE_LEVELS:
            supported = ", ".join(PERCENTILE_LEVELS)
            raise ValueError(f"unknown percentile {self.percentile!r} (supported: {supported})")
        if self.threshold_ms <= 0:
            raise ValueError(
                f"{self.percentile}: threshold must be positive, got {self.threshold_ms}"
            )


@dataclass(frozen=True, slots=True)
class LatencyBar:
    """The contract's latency dimension: resolved bounds, judged like any bar.

    Latency is conditioned on functional success — only passing samples'
    durations are judged — and gates the composite verdict by conjunction
    with the functional criteria. Declaring the bar is the opt-in; there
    is no advisory mode.

    Attributes:
        bounds: The asserted bounds, one per percentile, in tail order.
        origin: ``"explicit"`` (declared ceilings) or
            ``"baseline-derived"`` (order-statistic bounds from a measured
            baseline) — the family's latency-provenance vocabulary.
        confidence: For baseline-derived bounds, the one-sided confidence
            the derivation was performed at; recorded for explicit bounds.
        provenance: Where the declaration comes from (SLA reference, the
            baseline artefact's name, ...).
    """

    bounds: tuple[LatencyBound, ...]
    origin: str = "explicit"
    confidence: float = DEFAULT_CONFIDENCE_LEVEL
    provenance: ThresholdProvenance = field(default_factory=ThresholdProvenance)

    def __post_init__(self) -> None:
        if not self.bounds:
            raise ValueError("a latency bar declares at least one bound")
        if self.origin not in ("explicit", "baseline-derived"):
            raise ValueError(f"unknown latency origin {self.origin!r}")
        if not 0.0 < self.confidence < 1.0:
            raise ValueError(f"latency confidence must be in (0, 1), got {self.confidence}")
        labels = [bound.percentile for bound in self.bounds]
        if len(labels) != len(set(labels)):
            raise ValueError("a latency bar asserts each percentile at most once")
        ordered = sorted(self.bounds, key=lambda b: PERCENTILE_LEVELS[b.percentile])
        if list(self.bounds) != ordered:
            raise ValueError("latency bounds must be declared in percentile order")
        thresholds = [bound.threshold_ms for bound in self.bounds]
        if thresholds != sorted(thresholds):
            raise ValueError(
                "latency thresholds must be non-decreasing across percentiles: a "
                "tighter bound on a higher percentile contradicts itself"
            )


@dataclass(frozen=True, slots=True)
class ServiceContract(Generic[RequestT]):
    """A stochastic service under test: identity, invocation, and criteria.

    Attributes:
        contract_id: The contract's stable identifier; names run artefacts.
        invoke: The service under test (a :class:`Service`) -- accepts one
            input value (opaque to the engine; the declarative layer splats a
            tuple-valued input as positional arguments before it gets here),
            returns one response. An anticipated bad response is *returned*
            (for the criteria to judge); only genuine defects raise, and a
            raising invocation aborts the run.
        criteria: One or more criteria, each judged independently over the
            same samples.
        views: Named transformations of the response -- the transformation
            stage, declared once and shared: each view is computed at most
            once per response, lazily, by every consumer that names it.
            ``"raw"`` is reserved for the untransformed response and never
            appears here.
        latency: The contract's latency dimension, when one is asserted:
            resolved per-percentile bounds judged over passing samples'
            durations, gating the composite verdict by conjunction with
            the functional criteria.
    """

    contract_id: str
    invoke: Service[RequestT]
    criteria: tuple[Criterion, ...]
    views: Mapping[str, Callable[[str], object]] = field(default_factory=dict)
    latency: LatencyBar | None = None

    def __post_init__(self) -> None:
        if not self.contract_id:
            raise ValueError("contract_id must be non-empty")
        if not self.criteria:
            raise ValueError(f"contract {self.contract_id!r} declares no criteria")
        names = [criterion.name for criterion in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError(f"contract {self.contract_id!r} has duplicate criterion names")
        if "raw" in self.views:
            raise ValueError("'raw' is the reserved name of the untransformed response")
        declared = set(self.views) | {"raw"}
        for criterion in self.criteria:
            for postcondition in criterion.postconditions:
                if postcondition.view not in declared:
                    raise ValueError(
                        f"criterion {criterion.name!r}: postcondition "
                        f"{postcondition.name!r} names undeclared view "
                        f"{postcondition.view!r}"
                    )
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))

    @property
    def thresholded_criteria(self) -> tuple[Criterion, ...]:
        """The criteria that declare a threshold and therefore receive verdicts."""
        return tuple(c for c in self.criteria if c.is_thresholded)
