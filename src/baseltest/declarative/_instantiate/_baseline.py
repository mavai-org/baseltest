"""Empirical criteria: judging a test's bar-less criteria against a baseline.

Under ``test``, a criterion without a declared threshold is an empirical
criterion: when the baseline directory holds a matching baseline (same
contract, inputs fingerprint, and covariates), its bar is derived from
the baseline's recorded evidence at this run's own sample size — the
companion's sample-size-first rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path

from baseltest.baseline import (
    BaselineResolution,
    StoredBaseline,
    StoredCriterion,
    resolve_baseline,
)
from baseltest.contract import Criterion, Postcondition, ThresholdProvenance
from baseltest.engine import inputs_fingerprint
from baseltest.statistics import derive_sample_size_first, wilson_lower_bound

from .._parser import FORMAT_IDENTIFIER, ContractDeclaration, CriterionDeclaration
from .._registry import Registry
from ._postconditions import _build_criterion


@dataclass(frozen=True, slots=True)
class BaselineContext:
    """The resolved baseline a test's empirical criteria judged against —
    the identity and the weakest criterion's standing, for the report's
    sizing disclosures.

    ``weakest_effective_rate`` is the lowest effective baseline rate among
    the judged empirical criteria (the criterion closest to any tolerance,
    hence the one downsizing hurts first); ``weakest_threshold`` is that
    criterion's derived bar at this run's size.
    """

    source_file: str
    generated_at: str
    samples: int
    weakest_criterion: str
    weakest_effective_rate: float
    weakest_threshold: float


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
    return resolve_baseline(
        baseline_dir,
        declaration.contract,
        inputs_fingerprint(declaration.inputs),
        {
            "taskFormat": FORMAT_IDENTIFIER,
            "binding": declaration.service,
            **service_provenance,
        },
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
    samples: int,
    confidence: float,
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
    registry: Registry,
) -> tuple[Criterion, float, float]:
    """One empirical criterion made judgeable: bar derived at this run's size.

    Returns the criterion, its effective baseline rate (the Wilson lower
    bound stands in for a perfect baseline), and the derived bar.
    """
    built = _build_criterion(entry, confidence, expected, transforms, registry)
    derivation = derive_sample_size_first(
        evidence.successes, evidence.trials, samples, built.confidence
    )
    criterion = _replace(
        built,
        threshold=derivation.min_pass_rate,
        cutoff=derivation.cutoff,
        provenance=ThresholdProvenance(origin="empirical", contract_ref=stored.path.name),
    )
    effective_rate = (
        wilson_lower_bound(evidence.successes, evidence.trials, built.confidence)
        if evidence.successes == evidence.trials
        else evidence.successes / evidence.trials
    )
    return criterion, effective_rate, derivation.min_pass_rate


def _empirical_criteria(
    declared: Sequence[CriterionDeclaration],
    resolution: BaselineResolution | None,
    samples: int,
    confidence: float,
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
    registry: Registry,
) -> tuple[list[Criterion], list[tuple[str, str]], "BaselineContext | None"]:
    """Judge every declared empirical criterion against the resolved baseline.

    Returns the judgeable criteria, the ``(name, reason)`` pairs for those
    that could not be judged, and the baseline context for the report's
    sizing disclosures (``None`` when nothing was judged).
    """
    judged: list[Criterion] = []
    skipped: list[tuple[str, str]] = []
    weakest: tuple[float, str, float] | None = None  # (effective rate, name, threshold)
    for entry in declared:
        located = _baseline_evidence(entry, resolution)
        if isinstance(located, str):
            skipped.append((entry.name, located))
            continue
        stored, evidence = located
        criterion, effective_rate, threshold = _judge_against_baseline(
            entry, stored, evidence, samples, confidence, expected, transforms, registry
        )
        judged.append(criterion)
        # The weakest criterion is the one closest to any tolerance —
        # the one downsizing hurts first.
        if weakest is None or effective_rate < weakest[0]:
            weakest = (effective_rate, entry.name, threshold)
    return judged, skipped, _baseline_context(resolution, weakest)


def _baseline_context(
    resolution: BaselineResolution | None, weakest: tuple[float, str, float] | None
) -> "BaselineContext | None":
    """The judged baseline's identity and weakest standing, or ``None``."""
    if weakest is None:
        return None
    assert resolution is not None and resolution.baseline is not None
    stored = resolution.baseline
    return BaselineContext(
        source_file=stored.path.name,
        generated_at=stored.generated_at,
        samples=stored.sample_count,
        weakest_criterion=weakest[1],
        weakest_effective_rate=weakest[0],
        weakest_threshold=weakest[2],
    )
