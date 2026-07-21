"""The baseline record: what a measurement run durably states about a service."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from baseltest.engine import LatencyBlock, RunResult, latency_block


class JudgementState(StrEnum):
    """A measurement-time normative judgement's outcome.

    The schema also reserves ``unsupportable`` for callers whose sample size
    was not validated up front; baseltest validates every run's size before
    sampling, so it emits only ``met`` or ``failed``.
    """

    MET = "met"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NormativeJudgement:
    """The measurement-time judgement of one criterion against its declared threshold.

    Purely documentary: a later reader sees not only what was measured but
    how the measurement stood relative to a bar in force at measurement
    time. It never affects how the artefact is consumed.

    Attributes:
        state: The :class:`JudgementState` reached against the bar.
        stipulated_threshold: The declared threshold judged against.
        confidence: The confidence level of the judgement.
    """

    state: JudgementState
    stipulated_threshold: float
    confidence: float


@dataclass(frozen=True, slots=True)
class CriterionCharacterisation:
    """One criterion's measured characterisation.

    Attributes:
        successes: Passing trials.
        trials: Total trials.
        failure_distribution: Failure reasons and their counts; empty when
            every trial passed.
        judgement: The measurement-time judgement, when the criterion
            declared a threshold; ``None`` otherwise.
    """

    successes: int
    trials: int
    failure_distribution: Mapping[str, int] = field(default_factory=dict)
    judgement: NormativeJudgement | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "failure_distribution", MappingProxyType(dict(self.failure_distribution))
        )

    @property
    def observed_rate(self) -> float:
        """The observed pass rate. A recorded characterisation has at least
        one trial."""
        return self.successes / self.trials


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    """Everything the baseline artefact states.

    Attributes:
        contract_id: The measured contract's identity.
        generated_at: Measurement time, UTC.
        sample_count: The run's total sample count.
        inputs_identity: Order-insensitive fingerprint of the input list.
        criteria: Per-criterion characterisations, keyed by criterion name,
            in declaration order.
        provenance: Additional provenance the caller supplies (e.g. the
            contract-format identifier, the resolved binding's name). String
            keys and values; recorded verbatim.
        latency: The gated aggregate-latency summary, carrying the full
            ascending vector of passing-sample durations — the raw material
            a later test needs to derive its own bound at its own
            confidence. ``None`` when no sample passed or no per-sample
            observations were recorded.
        views: Descriptive fingerprints of declared view output schemas
            that are NOT covariates, keyed by view name — visible and
            diffable in the artefact, never compared by baseline
            resolution (covariate fingerprints travel in ``provenance``
            instead). Additive, optional field of the artefact schema.
    """

    contract_id: str
    generated_at: datetime
    sample_count: int
    inputs_identity: str
    criteria: Mapping[str, CriterionCharacterisation]
    provenance: Mapping[str, str] = field(default_factory=dict)
    latency: LatencyBlock | None = None
    views: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))

    @staticmethod
    def from_run_result(
        result: RunResult,
        provenance: Mapping[str, str] | None = None,
        views: Mapping[str, str] | None = None,
    ) -> "BaselineRecord":
        """Build a record from a completed run.

        Thresholded criteria carry their measurement-time judgement
        (met/failed from the run's verdict); unthresholded criteria are
        characterised without one.
        """
        criteria: dict[str, CriterionCharacterisation] = {}
        for criterion_result in result.criterion_results:
            judgement = None
            if criterion_result.verdict is not None:
                criterion = criterion_result.criterion
                assert criterion.threshold is not None
                judgement = NormativeJudgement(
                    state=JudgementState.MET
                    if criterion_result.verdict.value == "pass"
                    else JudgementState.FAILED,
                    stipulated_threshold=criterion.threshold,
                    confidence=criterion.confidence,
                )
            tally = criterion_result.tally
            criteria[criterion_result.name] = CriterionCharacterisation(
                successes=tally.successes,
                trials=tally.trials,
                failure_distribution=dict(tally.failure_reasons),
                judgement=judgement,
            )
        return BaselineRecord(
            contract_id=result.contract_id,
            generated_at=result.finished_at,
            sample_count=result.plan.samples,
            inputs_identity=result.inputs_identity,
            criteria=criteria,
            provenance=dict(provenance or {}),
            latency=latency_block(result.samples),
            views=dict(views or {}),
        )
