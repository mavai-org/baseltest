"""Preflight: is the configuration valid before any sample runs?

Two configurations are refused before any invocation (§5.7.1), and a
refusal names every applicable code, in one fixed order, so a developer can
correct every part at once:

- ``TEST_LARGER_THAN_BASELINE`` — the test is planned larger than the
  baseline run it consumes; judged once on the two samplings, for every
  criterion the test carries, pass-rate and latency alike, whatever the
  intent;
- ``COMPLIANCE_INFEASIBLE`` — under verification intent, a normative design
  (a pass-rate requirement, or an explicit latency requirement) too small
  for any outcome to demonstrate compliance.

When any part is invalid the whole configuration is refused: a run never
proceeds half-valid. Only a test is refused — a measure run renders no
verdict, so an unsupportable bar is recorded rather than refused.
"""

from collections.abc import Sequence
from typing import Any

from baseltest.contract import BaseltestError, ServiceContract
from baseltest.statistics import (
    ConfigurationError,
    Intent,
    check_feasibility,
    check_test_size,
    ordered_configuration_errors,
)

from .model import RefusedPart, RunKind, RunPlan


def derive_minimum_samples(contract: ServiceContract[Any]) -> int:
    """The smallest sample count at which every declared requirement can pass.

    Per normative criterion, the feasibility minimum of the exact binomial
    test at its requirement and level; the governing minimum is the
    largest, since every criterion is evaluated over the same samples.

    Raises:
        ValueError: If the contract declares no requirement (an empirical
            or characterised criterion has no feasibility anchor).
    """
    required = [c for c in contract.criteria if c.threshold is not None]
    if not required:
        raise ValueError("cannot derive a sample count: no criterion declares a threshold")
    return max(
        check_feasibility(c.threshold, 1, c.alpha).minimum_samples
        for c in required
        if c.threshold is not None
    )


class ConfigurationRefusedError(BaseltestError):
    """The configuration is refused before any invocation.

    Carries every applicable code, in the fixed order, and the refused parts
    so the caller can render a constructive refusal (never this exception's
    bare text).
    """

    def __init__(self, samples: int, parts: Sequence[RefusedPart]) -> None:
        self.samples = samples
        self.parts = tuple(parts)
        self.errors = ordered_configuration_errors(part.code for part in self.parts)
        codes = " ".join(self.errors)
        subjects = ", ".join(part.subject for part in self.parts)
        super().__init__(f"configuration refused ({codes}): {subjects}")


def refused_parts(contract: ServiceContract[Any], plan: RunPlan) -> tuple[RefusedPart, ...]:
    """Every invalid part of a test's configuration, in the fixed code order."""
    parts: list[RefusedPart] = []
    baselines = [
        (criterion.name, criterion.baseline.trials)
        for criterion in contract.criteria
        if criterion.baseline is not None
    ]
    latency = contract.latency
    if latency is not None and latency.baseline is not None:
        baselines.append(("latency", latency.baseline.samples))
    for subject, baseline_samples in baselines:
        if check_test_size(baseline_samples, plan.samples) is not None:
            parts.append(
                RefusedPart(
                    ConfigurationError.TEST_LARGER_THAN_BASELINE,
                    subject,
                    plan.samples,
                    baseline_samples,
                )
            )
    if plan.intent is Intent.VERIFICATION:
        requirements = [
            (criterion.name, criterion.threshold, criterion.alpha)
            for criterion in contract.criteria
            if criterion.threshold is not None
        ]
        if latency is not None and latency.baseline is None:
            requirements.extend(
                (f"latency {bound.percentile}", bound.level, latency.alpha)
                for bound in latency.bounds
            )
        for subject, requirement, alpha in requirements:
            check = check_feasibility(requirement, plan.samples, alpha)
            if not check.feasible:
                parts.append(
                    RefusedPart(
                        ConfigurationError.COMPLIANCE_INFEASIBLE,
                        subject,
                        plan.samples,
                        check.minimum_samples,
                        requirement,
                    )
                )
    return tuple(parts)


def _preflight(contract: ServiceContract[Any], plan: RunPlan) -> None:
    """Refuse an invalid test configuration, whole, before any invocation."""
    if plan.kind is not RunKind.TEST:
        return
    parts = refused_parts(contract, plan)
    if parts:
        raise ConfigurationRefusedError(plan.samples, parts)
