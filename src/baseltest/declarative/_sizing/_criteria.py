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
from baseltest.statistics import check_feasibility, effective_baseline_rate

from .._parser import ContractDeclaration, CriterionDeclaration
from .._services import ServiceDefinition
from ._model import _EmpiricalCriterion, _UnsizeableCriterion

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


def _sizeable_criteria(
    declaration: ContractDeclaration,
    baseline: StoredBaseline,
    tolerate_flags: dict[str, float],
    confidence_flag: float | None,
) -> tuple[list[_EmpiricalCriterion], list[_UnsizeableCriterion]]:
    """The empirical criteria the baseline records, with claims resolved.

    Claim precedence per criterion: flag over contract key; an unclaimed
    criterion carries ``None`` and is the interactive mode's business.

    A criterion the baseline records as passing nothing comes back in the
    second list. Its effective rate is zero — the Wilson lower bound of no
    successes is exactly zero, at every sample size and every confidence —
    and the sizing construction needs a tolerated rate strictly below the
    baseline, which leaves nothing to ask for. That is a fact about the
    measurement, so it travels as one rather than as a violated precondition
    three frames further in.
    """
    sizeable = []
    unsizeable = []
    for entry in declaration.criteria:
        if entry.threshold is not None:
            continue
        evidence = baseline.criteria.get(entry.name)
        if evidence is None or evidence.trials == 0:
            continue  # instantiation reports the skip; there is nothing to size
        if evidence.successes == 0:
            # Decided on the count, not the derived rate: the count is what
            # the baseline document states.
            unsizeable.append(_UnsizeableCriterion(name=entry.name, trials=evidence.trials))
            continue
        confidence = _criterion_confidence(entry, declaration, confidence_flag)
        tolerated = tolerate_flags.get(entry.name)
        if tolerated is None:
            tolerated = entry.tolerate
        sizeable.append(
            _EmpiricalCriterion(
                name=entry.name,
                baseline_rate=effective_baseline_rate(
                    evidence.successes, evidence.trials, confidence
                ),
                baseline_trials=evidence.trials,
                confidence=confidence,
                tolerated_rate=tolerated,
            )
        )
    return sizeable, unsizeable


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
