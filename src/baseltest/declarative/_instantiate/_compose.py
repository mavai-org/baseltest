"""The ``test``/``measure`` composition: a declaration into contract and plan.

The run mode is supplied by the invocation (the verb), never by the file:
``test`` instantiates a probabilistic test over the thresholded criteria
(criteria without a bar are skipped, reported by name — never silently);
``measure`` instantiates a measure experiment over every criterion.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baseltest.contract import ServiceContract
from baseltest.engine import RunKind, RunPlan

from .._errors import ContractConfigurationError
from .._parser import ContractDeclaration
from .._registry import Registry
from .._schema_walk import validate_declared_paths
from .._services import ServiceDefinition
from ._baseline import BaselineContext, _empirical_criteria, _resolve_matching_baseline
from ._latency import _latency_bar
from ._postconditions import _build_criterion, _expected_postconditions
from ._service import _resolve_service, _splat_tuple_invoke, _validate_inputs, validate_media
from ._sizing_policy import RunSizing, _resolve_run_size
from ._views import _build_views


@dataclass(frozen=True, slots=True)
class Instantiation:
    """A declaration made runnable under a mode — contract, plan, and disclosures.

    Attributes:
        contract: The live service contract the engine runs.
        plan: The run plan (N, inputs, kind, intent).
        sizing: The run's N and its provenance — the run-plan line's data.
        service_provenance: The resolved service's covariates.
        skipped: Under ``test``, the ``(name, reason)`` pairs for empirical
            criteria that could not be judged (no matching baseline).
        baseline_context: The resolved baseline's context when empirical
            criteria were judged against one (the report's sizing
            disclosures read it); ``None`` otherwise.
    """

    contract: ServiceContract[Any]
    plan: RunPlan
    sizing: RunSizing
    service_provenance: dict[str, str]
    skipped: tuple[tuple[str, str], ...]
    baseline_context: BaselineContext | None


def instantiate(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None,
    registry: Registry,
    mode: RunKind = RunKind.TEST,
    samples: int | None = None,
    baseline_dir: Path | None = None,
    samples_provenance: str | None = None,
) -> Instantiation:
    """Instantiate the contract and plan for a contract declaration under a run mode.

    Returns the contract, the run plan, the run's sizing (N and its
    provenance — the run-plan line's data), the resolved service
    provenance, — under ``test`` — the ``(name, reason)`` pairs for
    empirical criteria that could not be judged (no matching baseline),
    and the resolved baseline's context when empirical criteria were
    judged against one (the report's sizing disclosures read it).

    Under ``test``, a criterion without a declared threshold is an
    empirical criterion: when ``baseline_dir`` holds a matching baseline
    (same contract, inputs fingerprint, and covariates), its bar is derived
    from the baseline's recorded evidence at this run's own sample size —
    the companion's sample-size-first rule — and it is judged like its
    normative siblings, with provenance naming the artefact.

    Raises:
        ContractConfigurationError: On any load-time refusal — before any
            invocation. In particular, a ``test`` where nothing is
            judgeable, a silently derived N above the derivation gate's
            limit, and a ``measure`` without an explicit sample count.
    """
    resolved, service_provenance = _resolve_service(declaration.service, services or {}, registry)
    _validate_inputs(declaration.service, resolved, declaration.inputs)
    definition = (services or {}).get(declaration.service)
    validate_media(definition.configuration if definition else None, declaration.inputs)
    response_schema = (
        getattr(definition.configuration, "response_schema", None) if definition else None
    )
    validate_declared_paths(declaration, response_schema, declaration.service, registry)
    invoke = _splat_tuple_invoke(resolved)
    transforms = declaration.transforms
    views = _build_views(declaration, registry)
    expected = _expected_postconditions(declaration.expected_pairs, transforms, registry)

    skipped: list[tuple[str, str]] = []
    if mode is RunKind.TEST:
        normative = [
            _build_criterion(entry, declaration.confidence, expected, transforms, registry)
            for entry in declaration.criteria
            if entry.threshold is not None
        ]
        empirical_declared = [c for c in declaration.criteria if c.threshold is None]
        sizing = _resolve_run_size(mode, declaration.intent, samples, normative, samples_provenance)
        resolution = _resolve_matching_baseline(
            declaration, empirical_declared, service_provenance, baseline_dir
        )
        latency_bar = _latency_bar(declaration, sizing.samples, resolution)
        empirical, skipped, baseline_context = _empirical_criteria(
            empirical_declared,
            resolution,
            sizing.samples,
            declaration.confidence,
            expected,
            transforms,
            registry,
        )
        criteria = tuple(normative + empirical)
        if not criteria:
            detail = f" ({skipped[0][1]})" if skipped else ""
            raise ContractConfigurationError(
                "nothing to test: no criterion declares a `threshold:` and no "
                f"empirical criterion could be judged{detail}. Run `baseltest "
                "measure` to establish a baseline, or declare a bar."
            )
    else:
        criteria = tuple(
            _build_criterion(entry, declaration.confidence, expected, transforms, registry)
            for entry in declaration.criteria
        )
        sizing = _resolve_run_size(mode, declaration.intent, samples, criteria)
        # A declared latency bar is a test-time assertion; a measure run's
        # product — the baseline's latency profile — is what it derives from.
        latency_bar = None
        baseline_context = None

    contract = ServiceContract(
        contract_id=declaration.contract,
        invoke=invoke,
        criteria=criteria,
        views=views,
        latency=latency_bar,
    )
    plan = RunPlan(
        samples=sizing.samples,
        inputs=declaration.inputs,
        kind=mode,
        intent=declaration.intent,
    )
    return Instantiation(
        contract=contract,
        plan=plan,
        sizing=sizing,
        service_provenance=service_provenance,
        skipped=tuple(skipped),
        baseline_context=baseline_context,
    )
