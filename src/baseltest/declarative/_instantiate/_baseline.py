"""Empirical criteria: judging a test's bar-less criteria against a baseline.

Under ``test``, a criterion without a declared threshold is an empirical
criterion: when the baseline directory holds a matching baseline (same
contract, inputs fingerprint, and covariates), it carries the baseline's
recorded evidence, and the engine derives its ``regression/fisher`` cutoff
at the run's own sample size.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path

from baseltest.baseline import (
    BaselineResolution,
    StoredBaseline,
    StoredCriterion,
    resolve_baseline,
)
from baseltest.contract import BaselineCount, Criterion, Postcondition, ThresholdProvenance
from baseltest.engine import inputs_fingerprint

from .._parser import ContractDeclaration, CriterionDeclaration
from .._registry import Registry
from ._postconditions import _build_criterion


@dataclass(frozen=True, slots=True)
class BaselineContext:
    """The resolved baseline a test's empirical criteria are judged against —
    its identity, for the report's sizing disclosures."""

    source_file: str
    generated_at: str
    samples: int


def _resolve_matching_baseline(
    declaration: ContractDeclaration,
    empirical_declared: Sequence[CriterionDeclaration],
    service_provenance: dict[str, str],
    baseline_dir: Path | None,
) -> BaselineResolution | None:
    """The baseline resolution a test's empirical needs call for, or ``None``.

    Resolution is attempted only when something will consume it — a
    bar-less criterion or an empirical latency declaration — and a
    baseline directory was given.
    """
    needs_baseline = bool(empirical_declared) or (
        declaration.latency is not None and bool(declaration.latency.empirical)
    )
    if not needs_baseline or baseline_dir is None:
        return None
    # Identity is the tuple: contract, service, inputs, covariates. The
    # service is now stated in its own right rather than compared as a
    # pseudo-covariate, and `taskFormat` leaves the comparison entirely —
    # a contract-format identifier does not change the distribution being
    # measured, so it is provenance (area rule 7).
    return resolve_baseline(
        baseline_dir,
        declaration.contract,
        declaration.service,
        inputs_fingerprint(declaration.inputs),
        dict(service_provenance),
    )


def _baseline_evidence(
    entry: CriterionDeclaration, resolution: BaselineResolution | None
) -> tuple[StoredBaseline, StoredCriterion] | str:
    """One criterion's baseline evidence, or the plain reason it has none."""
    if resolution is None or not resolution.matched:
        reason = (
            resolution.reason
            if resolution is not None and resolution.reason
            else "requires a baseline"
        )
        return f"{reason} — run `basel measure` first"
    stored = resolution.baseline
    assert stored is not None
    evidence = stored.criteria.get(entry.name)
    if evidence is None or evidence.trials == 0:
        return (
            f"baseline {stored.path.name} does not record this criterion — re-run `basel measure`"
        )
    return stored, evidence


def _judge_against_baseline(
    entry: CriterionDeclaration,
    stored: StoredBaseline,
    evidence: StoredCriterion,
    confidence: float,
    design_alternative_rate: float | None,
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
    registry: Registry,
) -> Criterion:
    """One empirical criterion made judgeable: it carries its baseline evidence."""
    built = _build_criterion(entry, confidence, expected, transforms, registry)
    return _replace(
        built,
        baseline=BaselineCount(successes=evidence.successes, trials=evidence.trials),
        design_alternative_rate=design_alternative_rate,
        provenance=ThresholdProvenance(origin="empirical", contract_ref=stored.path.name),
    )


def _empirical_criteria(
    declared: Sequence[CriterionDeclaration],
    resolution: BaselineResolution | None,
    confidence: float,
    design_alternative_rates: Mapping[str, float],
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
    registry: Registry,
) -> tuple[list[Criterion], list[tuple[str, str]], "BaselineContext | None"]:
    """Judge every declared empirical criterion against the resolved baseline.

    A criterion's design alternative rate is the one the sizing
    conversation resolved for it, else its own ``tolerate:`` declaration.

    Returns the judgeable criteria, the ``(name, reason)`` pairs for those
    that could not be judged, and the baseline context for the report's
    sizing disclosures (``None`` when nothing was judged).
    """
    judged: list[Criterion] = []
    skipped: list[tuple[str, str]] = []
    for entry in declared:
        located = _baseline_evidence(entry, resolution)
        if isinstance(located, str):
            skipped.append((entry.name, located))
            continue
        stored, evidence = located
        judged.append(
            _judge_against_baseline(
                entry,
                stored,
                evidence,
                confidence,
                design_alternative_rates.get(entry.name, entry.tolerate),
                expected,
                transforms,
                registry,
            )
        )
    context = None
    if judged:
        assert resolution is not None and resolution.baseline is not None
        stored = resolution.baseline
        context = BaselineContext(
            source_file=stored.path.name,
            generated_at=stored.generated_at,
            samples=stored.sample_count,
        )
    return judged, skipped, context
