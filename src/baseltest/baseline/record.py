"""The baseline record: what a measurement run durably states about a service."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from baseltest.contract import FailureAxis, PostconditionStanding
from baseltest.engine import LatencyBlock, RunResult, latency_block
from baseltest.statistics import DEFAULT_CONFIDENCE_LEVEL, wilson_lower_bound


class CriterionMode(StrEnum):
    """Whether a criterion estimates a proportion (companion §1.5).

    An observational criterion states no rate and no bound: it estimates no
    proportion at all, passing iff no failure was observed.
    """

    INFERENTIAL = "inferential"
    OBSERVATIONAL = "observational"


class CriterionProcedure(StrEnum):
    """The inferential procedure a criterion is judged under."""

    REGRESSION = "REGRESSION"
    COMPLIANCE = "COMPLIANCE"


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
        standings: The criterion's descriptive per-postcondition tally —
            per ``(input, check)``, passed/failed/skipped counts and the
            observed fraction, each row carrying its check's optional
            flag. Triage data, additive in the artefact schema; never an
            interval or a per-check verdict.
        optional_slack: The criterion's declared optional-check failure
            budget, verbatim as authored (``None`` when undeclared —
            never ``"0"``). Additive in the artefact schema.
    """

    successes: int
    trials: int
    failure_distribution: Mapping[str, int] = field(default_factory=dict)
    failure_axes: Mapping[str, FailureAxis] = field(default_factory=dict)
    judgement: NormativeJudgement | None = None
    standings: tuple[PostconditionStanding, ...] = ()
    optional_slack: str | None = None
    mode: CriterionMode = CriterionMode.INFERENTIAL
    procedure: CriterionProcedure | None = CriterionProcedure.REGRESSION
    wilson_lower_bound: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "failure_distribution", MappingProxyType(dict(self.failure_distribution))
        )
        object.__setattr__(self, "failure_axes", MappingProxyType(dict(self.failure_axes)))

    @property
    def observed_rate(self) -> float:
        """The observed pass rate. A recorded characterisation has at least
        one trial."""
        return self.successes / self.trials


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    """Everything the baseline artefact states.

    Attributes:
        service_contract_id: The measured service contract's identity.
        service_name: The name of the service that was invoked. Identity,
            not provenance: a contract may exercise several services and a
            service may be the subject of several contracts, so neither
            names a record alone.
        generated_at: Measurement time, UTC.
        confidence_level: The level every ``wilson_lower_bound`` in this
            record was computed at. Distinct from a criterion's stipulated
            ``NormativeJudgement.confidence``, which need not agree.
        inputs_identity: Order-insensitive fingerprint of the input list.
        samples_planned: Trials asked for.
        samples_executed: Trials actually run. Equal to ``samples_planned``
            until early termination exists; sourced from the run either way,
            never assumed by the writer.
        termination_reason: Why the run ended.
        covariate_profile: The resolved covariate values — identity.
        factor_record: Run provenance. Never compared by resolution.
        criteria: Per-criterion characterisations, keyed by criterion name,
            in declaration order.
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

    service_contract_id: str
    service_name: str
    generated_at: datetime
    confidence_level: float
    inputs_identity: str
    samples_planned: int
    samples_executed: int
    criteria: Mapping[str, CriterionCharacterisation]
    termination_reason: str = "COMPLETED"
    covariate_profile: Mapping[str, str] = field(default_factory=dict)
    factor_record: Mapping[str, str] = field(default_factory=dict)
    latency: LatencyBlock | None = None
    views: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", MappingProxyType(dict(self.views)))

    @staticmethod
    def from_run_result(
        result: RunResult,
        service_name: str,
        covariate_profile: Mapping[str, str] | None = None,
        factor_record: Mapping[str, str] | None = None,
        views: Mapping[str, str] | None = None,
        confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    ) -> "BaselineRecord":
        """Build a record from a completed run.

        Thresholded criteria carry their measurement-time judgement
        (met/failed from the run's verdict); unthresholded criteria are
        characterised without one.

        The Wilson lower bound is computed here, where the counts and the
        confidence level are both in hand — never in the writer, which
        states what the record holds and derives nothing.
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
            slack = criterion_result.criterion.optional_slack
            criteria[criterion_result.name] = CriterionCharacterisation(
                successes=tally.successes,
                trials=tally.trials,
                failure_distribution=dict(tally.failure_reasons),
                failure_axes=dict(tally.failure_axes),
                judgement=judgement,
                standings=criterion_result.standings,
                optional_slack=slack.declared if slack is not None else None,
                wilson_lower_bound=(
                    wilson_lower_bound(tally.successes, tally.trials, confidence_level)
                    if tally.trials
                    else None
                ),
            )
        # Every criterion sees every sample, so any criterion's trial count
        # is the run's executed count (companion §1.4.5a). Sourced rather
        # than assumed equal to the plan: when early termination lands, this
        # already states the truth.
        executed = max((r.tally.trials for r in result.criterion_results), default=0)
        return BaselineRecord(
            service_contract_id=result.contract_id,
            service_name=service_name,
            generated_at=result.finished_at,
            confidence_level=confidence_level,
            inputs_identity=result.inputs_identity,
            samples_planned=result.plan.samples,
            samples_executed=executed,
            criteria=criteria,
            covariate_profile=dict(covariate_profile or {}),
            factor_record=dict(factor_record or {}),
            latency=latency_block(result.samples),
            views=dict(views or {}),
        )
