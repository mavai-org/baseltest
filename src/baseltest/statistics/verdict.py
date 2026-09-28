"""Verdicts: one criterion under its rule, and their composition (§1.4.6, §12.3.2).

A criterion is decided by the rule its threshold's origin selects:

- a **given** (normative) requirement by ``compliance/exact-binomial`` —
  :func:`evaluate_compliance`;
- a **baseline-derived** (empirical) bar by ``regression/fisher`` —
  :func:`evaluate_regression`.

Criteria compose by one structural rule — PASS if every verdict passes, FAIL
if any fails, INCONCLUSIVE otherwise — and the same rule composes the
functional dimension ``V_rate`` with the latency dimension ``V_latency`` into
the test's verdict ``V_test``. A FAIL or an INCONCLUSIVE names what decided
it. The Type-I envelopes are disclosed by procedure direction: the sum of
alpha over the compliance decisions (false compliance) and over the
regression decisions (false degradation signal).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import ClassVar

from scipy.stats import binom

from ._validation import validate_counts
from .compliance import clopper_pearson_lower, minimum_passing_count
from .regression import RegressionDerivation, derive_regression_cutoff
from .rules import DecisionRule


class Verdict(Enum):
    """The outcome of a criterion, a dimension, or a test."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def structural_composite(verdicts: Iterable[Verdict]) -> Verdict:
    """PASS if every verdict passes, FAIL if any fails, INCONCLUSIVE otherwise.

    Raises:
        ValueError: On no verdicts — there is nothing to compose.
    """
    collected = list(verdicts)
    if not collected:
        raise ValueError("a composite needs at least one verdict")
    if all(v is Verdict.PASS for v in collected):
        return Verdict.PASS
    if any(v is Verdict.FAIL for v in collected):
        return Verdict.FAIL
    return Verdict.INCONCLUSIVE


@dataclass(frozen=True, slots=True)
class ComplianceVerdict:
    """A criterion decided by ``compliance/exact-binomial``.

    Attributes:
        verdict: PASS iff ``K >= k_min``. FAIL means compliance was not
            demonstrated — including when no count can pass at this size
            (``pass_possible`` false), where the FAIL was certain before the
            run and carries no evidence about the service.
        successes: ``K``.
        trials: ``n``.
        requirement: ``p_req``.
        alpha: The one-sided level.
        minimum_passing: ``k_min``; ``None`` when no count can pass.
        false_compliance: ``P_{p_req}(K >= k_min)``, 0 when no count can pass.
        clopper_pearson_lower: The one-sided lower bound at ``1 - alpha``,
            reported beside the verdict; it decides nothing.
    """

    rule: ClassVar[DecisionRule] = DecisionRule.COMPLIANCE_EXACT_BINOMIAL

    verdict: Verdict
    successes: int
    trials: int
    requirement: float
    alpha: float
    minimum_passing: int | None
    false_compliance: float
    clopper_pearson_lower: float

    @property
    def pass_possible(self) -> bool:
        """Whether any outcome of this size could have passed."""
        return self.minimum_passing is not None

    @property
    def observed_rate(self) -> float:
        """``K / n``, for context: it can sit above the requirement while
        compliance is not demonstrated."""
        return self.successes / self.trials


def evaluate_compliance(
    successes: int, trials: int, requirement: float, alpha: float
) -> ComplianceVerdict:
    """Decide a criterion against a given requirement.

    Raises:
        ValueError: On counts out of range, or a requirement or level
            outside ``(0, 1)``.
    """
    validate_counts(successes, trials)
    k_min = minimum_passing_count(requirement, trials, alpha)
    passed = k_min is not None and successes >= k_min
    return ComplianceVerdict(
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        successes=successes,
        trials=trials,
        requirement=requirement,
        alpha=alpha,
        minimum_passing=k_min,
        false_compliance=0.0 if k_min is None else float(binom.sf(k_min - 1, trials, requirement)),
        clopper_pearson_lower=clopper_pearson_lower(successes, trials, alpha),
    )


@dataclass(frozen=True, slots=True)
class RegressionVerdict:
    """A criterion decided by ``regression/fisher``.

    Attributes:
        verdict: PASS iff ``K_t >= cutoff``.
        successes: ``K_t``.
        trials: ``n_t``.
        baseline_successes: ``K_b``.
        baseline_trials: ``n_b``.
        derivation: The cutoff and what the report discloses about it.
    """

    rule: ClassVar[DecisionRule] = DecisionRule.REGRESSION_FISHER

    verdict: Verdict
    successes: int
    trials: int
    baseline_successes: int
    baseline_trials: int
    derivation: RegressionDerivation

    @property
    def cutoff(self) -> int:
        """The binding decision artefact."""
        return self.derivation.cutoff

    @property
    def alpha(self) -> float:
        """The one-sided level."""
        return self.derivation.alpha

    @property
    def observed_rate(self) -> float:
        """``K_t / n_t``; it passes exactly when it reaches ``cutoff / n_t``."""
        return self.successes / self.trials


def evaluate_regression(
    successes: int,
    trials: int,
    baseline_successes: int,
    baseline_trials: int,
    alpha: float,
) -> RegressionVerdict:
    """Decide a criterion against its baseline.

    The design rule that a test may not exceed its baseline is judged
    before the run (``rules.check_test_size``), not here.

    Raises:
        ValueError: On counts out of range or a level outside ``(0, 1)``.
    """
    validate_counts(successes, trials)
    derivation = derive_regression_cutoff(baseline_successes, baseline_trials, trials, alpha)
    return RegressionVerdict(
        verdict=Verdict.PASS if successes >= derivation.cutoff else Verdict.FAIL,
        successes=successes,
        trials=trials,
        baseline_successes=baseline_successes,
        baseline_trials=baseline_trials,
        derivation=derivation,
    )


class Direction(StrEnum):
    """The error event a decision's alpha bounds, for the envelopes (§1.4.6)."""

    COMPLIANCE = "COMPLIANCE"
    """A false claim of compliance: compliance criteria and enforced
    explicit latency requirements."""

    REGRESSION = "REGRESSION"
    """A false degradation signal: regression criteria and enforced
    baseline-derived latency constraints."""


def direction_of(rule: DecisionRule) -> Direction:
    """The direction whose envelope a rule's decisions enter."""
    if rule in (
        DecisionRule.COMPLIANCE_EXACT_BINOMIAL,
        DecisionRule.LATENCY_COMPLIANCE_EXACT_BINOMIAL,
    ):
        return Direction.COMPLIANCE
    return Direction.REGRESSION


@dataclass(frozen=True, slots=True)
class Envelopes:
    """The union-bound Type-I envelopes, split by direction.

    Each is ``None`` when the test makes no decision of that direction.
    """

    false_compliance: float | None
    false_degradation_signal: float | None


def type_one_envelopes(decisions: Iterable[tuple[DecisionRule, float]]) -> Envelopes:
    """Sum each direction's alphas over the ``(rule, alpha)`` decisions made."""
    sums: dict[Direction, float] = {}
    for rule, alpha in decisions:
        direction = direction_of(rule)
        sums[direction] = sums.get(direction, 0.0) + alpha
    return Envelopes(
        false_compliance=sums.get(Direction.COMPLIANCE),
        false_degradation_signal=sums.get(Direction.REGRESSION),
    )


class TriggerKind(StrEnum):
    """What decided a test's FAIL or INCONCLUSIVE."""

    CRITERION = "criterion"
    LATENCY = "latency"


@dataclass(frozen=True, slots=True)
class Trigger:
    """One functional criterion or enforced latency constraint that decided the test."""

    kind: TriggerKind
    id: str


@dataclass(frozen=True, slots=True)
class OverallVerdict:
    """The test's verdict ``V_test`` and the two dimensions it composes.

    Attributes:
        rate_verdict: ``V_rate``, the composite of the functional criteria;
            ``None`` for a test with none.
        latency_verdict: ``V_latency``, the composite of the enforced latency
            constraints; ``None`` for a test that enforces none.
        verdict: ``V_test``, the composite of the dimensions present.
        triggering: For a FAIL or an INCONCLUSIVE, the criteria and enforced
            constraints whose verdict is the test's, criteria first.
    """

    rate_verdict: Verdict | None
    latency_verdict: Verdict | None
    verdict: Verdict
    triggering: tuple[Trigger, ...]


def compose_overall_verdict(
    criteria: Sequence[tuple[str, Verdict]], latency: Sequence[tuple[str, Verdict]] = ()
) -> OverallVerdict:
    """Compose ``V_test`` from ``(id, verdict)`` pairs of the functional criteria
    and of the enforced latency constraints (advisory ones never enter).

    Raises:
        ValueError: When there is neither a criterion nor an enforced
            latency constraint to compose.
    """
    rate = structural_composite(v for _, v in criteria) if criteria else None
    latency_verdict = structural_composite(v for _, v in latency) if latency else None
    overall = structural_composite(v for v in (rate, latency_verdict) if v is not None)
    triggering: tuple[Trigger, ...] = ()
    if overall is not Verdict.PASS:
        triggering = tuple(
            Trigger(TriggerKind.CRITERION, name) for name, v in criteria if v is overall
        ) + tuple(Trigger(TriggerKind.LATENCY, name) for name, v in latency if v is overall)
    return OverallVerdict(
        rate_verdict=rate, latency_verdict=latency_verdict, verdict=overall, triggering=triggering
    )
