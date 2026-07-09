"""The baseline record: what a measurement run durably states about a service."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from baseltest.engine import LatencyBlock, RunResult, latency_block


@dataclass(frozen=True, slots=True)
class NormativeJudgement:
    """The measurement-time judgement of one criterion against its declared threshold.

    Purely documentary: a later reader sees not only what was measured but
    how the measurement stood relative to a bar in force at measurement
    time. It never affects how the artefact is consumed.

    Attributes:
        state: ``"met"`` or ``"failed"`` (the schema reserves
            ``"unsupportable"`` for callers whose sample size was not
            validated up front).
        stipulated_threshold: The declared threshold judged against.
        confidence: The confidence level of the judgement.
    """

    state: str
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

    @property
    def observed_rate(self) -> float:
        """The observed pass rate; 0.0 with no trials."""
        return self.successes / self.trials if self.trials else 0.0


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
    """

    contract_id: str
    generated_at: datetime
    sample_count: int
    inputs_identity: str
    criteria: Mapping[str, CriterionCharacterisation]
    provenance: Mapping[str, str] = field(default_factory=dict)
    latency: LatencyBlock | None = None

    @staticmethod
    def from_run_result(
        result: RunResult, provenance: Mapping[str, str] | None = None
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
                    state="met" if criterion_result.verdict.value == "pass" else "failed",
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
        )
