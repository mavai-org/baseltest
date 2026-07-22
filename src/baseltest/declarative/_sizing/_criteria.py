"""Baseline resolution and the sizeable-criteria selection.

The baseline the empirical criteria would judge against (resolved by the
same identity keys the run uses), the empirical criteria that baseline can
price with their claims resolved, and the feasibility floor the normative
criteria put under any run size.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from baseltest.baseline import BaselineResolution, StoredBaseline, resolve_baseline
from baseltest.engine import inputs_fingerprint
from baseltest.statistics import check_feasibility

from .._parser import FORMAT_IDENTIFIER, ContractDeclaration, CriterionDeclaration
from .._services import ServiceDefinition
from ._model import _EmpiricalCriterion
from ._rates import _effective_rate

if TYPE_CHECKING:
    from .._registry import Registry


def resolve_contract_baseline(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition],
    baseline_dir: Path,
    registry: "Registry",
) -> BaselineResolution:
    """The resolution of the baseline the empirical criteria would judge against.

    Mirrors the instantiation-time resolution (same identity keys), so the
    sizing conversation prices exactly the baseline the run will judge
    against — and a non-match carries the honest reason (a drifted
    covariate is named, never flattened into "no baseline").
    """
    definition = services.get(declaration.service)
    if definition is not None:
        service_provenance = definition.type.provenance(definition.configuration)
    else:
        type_contract = registry.find_type(declaration.service)
        service_provenance = (
            dict(type_contract.covariates)
            if type_contract is not None and type_contract.addressable
            else {}
        )
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


def _sizeable_criteria(
    declaration: ContractDeclaration,
    baseline: StoredBaseline,
    tolerate_flags: dict[str, float],
    confidence_flag: float | None,
) -> list[_EmpiricalCriterion]:
    """The empirical criteria the baseline records, with claims resolved.

    Claim precedence per criterion: flag over contract key; an unclaimed
    criterion carries ``None`` and is the interactive mode's business.
    """
    sizeable = []
    for entry in declaration.criteria:
        if entry.threshold is not None:
            continue
        evidence = baseline.criteria.get(entry.name)
        if evidence is None or evidence.trials == 0:
            continue  # instantiation reports the skip; there is nothing to size
        confidence = _criterion_confidence(entry, declaration, confidence_flag)
        tolerated = tolerate_flags.get(entry.name)
        if tolerated is None:
            tolerated = entry.tolerate
        sizeable.append(
            _EmpiricalCriterion(
                name=entry.name,
                baseline_rate=_effective_rate(evidence.successes, evidence.trials, confidence),
                baseline_trials=evidence.trials,
                confidence=confidence,
                tolerated_rate=tolerated,
            )
        )
    return sizeable


def _criterion_confidence(
    entry: CriterionDeclaration,
    declaration: ContractDeclaration,
    confidence_flag: float | None,
) -> float:
    if confidence_flag is not None:
        return confidence_flag
    if entry.confidence is not None:
        return entry.confidence
    return declaration.confidence


def _normative_minimum(declaration: ContractDeclaration) -> int:
    """The feasibility floor the normative criteria put under any run size."""
    minima = [
        check_feasibility(
            1, entry.threshold, _criterion_confidence(entry, declaration, None)
        ).minimum_samples
        for entry in declaration.criteria
        if entry.threshold is not None
    ]
    return max(minima, default=0)
