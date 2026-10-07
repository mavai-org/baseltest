"""The ``test``/``measure`` verb: load, instantiate, execute, render, persist.

Persistence strictly precedes rendering and any downstream assertion: for a
measure run the baseline artefact is on disk before ``run`` returns.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import (
    ConfigurationRefusedError,
    Dimension,
    RunKind,
    RunResult,
    execute,
    inputs_fingerprint,
    plan_latency,
)
from baseltest.reporting import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    render_latency_planning,
    render_run,
    render_run_plan,
    write_refused_record,
    write_verdict_record,
)
from baseltest.statistics import RegressionVerdict

from .._instantiate import BaselineContext, descriptive_view_fingerprints, instantiate
from .._parser import FORMAT_IDENTIFIER
from .._registry import Bindings
from .._sizing import ResolvedSizing
from ._load import LoadedContract, load_for_run
from ._shared import DEFAULT_BASELINE_DIR, _tty_progress

if TYPE_CHECKING:
    from .._parser._model import ContractDeclaration
    from .._services._model import ServiceDefinition


def run(
    path: str | Path,
    mode: str | RunKind = RunKind.TEST,
    *,
    samples: int | None = None,
    samples_provenance: str | None = None,
    sizing_resolution: ResolvedSizing | None = None,
    baseline_dir: str | Path = DEFAULT_BASELINE_DIR,
    verdict_dir: str | Path | None = None,
    emit: bool = True,
    bindings: Bindings | None = None,
    loaded: LoadedContract | None = None,
    advisory: frozenset[Dimension] = frozenset(),
) -> RunResult:
    """Load and execute a contract file; render its output; persist when measuring.

    Persistence strictly precedes rendering and any downstream assertion:
    for a measure run the baseline artefact is on disk before this
    function returns.

    Args:
        path: The contract file.
        sizing_resolution: The CLI's resolved risk-driven sizing, when the
            invocation went through the sizing conversation — supplies the
            sample count, its provenance, and the recorded design claims.
        baseline_dir: Where measure runs persist their baseline artefact.
        emit: Whether to print the rendered output (the CLI does; API
            callers may render from the returned result instead).
        loaded: The contract's already-parsed declaration, registry, and
            services. The ``test`` verb sizes the run before executing it and
            passes what it parsed here so the run does not re-read the same
            files; when absent (measure, API callers) the run loads them itself.
        advisory: The dimensions this run makes advisory — decided and
            reported, never failing the test. Empty, every assertion is
            enforced. An operator's run-time choice, never a contract's.

    Returns:
        The run result.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation.
        ConfigurationRefusedError: The configuration is refused before any
            invocation — a test larger than its baseline, or a requirement
            no outcome of this size can demonstrate under verification
            intent — naming every applicable code. Under ``test`` with a
            verdict directory, the refused record is written first.
    """
    run_mode = RunKind(mode) if isinstance(mode, str) else mode
    if sizing_resolution is not None:
        samples = sizing_resolution.samples if samples is None else samples
        samples_provenance = samples_provenance or sizing_resolution.provenance
    contract_path = Path(path)
    if loaded is None:
        loaded = load_for_run(contract_path, bindings)
    declaration = loaded.declaration
    registry = loaded.registry
    services = loaded.services
    instantiation = instantiate(
        declaration,
        services,
        registry,
        mode=run_mode,
        samples=samples,
        baseline_dir=Path(baseline_dir),
        samples_provenance=samples_provenance,
        design_alternative_rates=(
            sizing_resolution.design_alternative_rates if sizing_resolution is not None else None
        ),
    )
    contract = instantiation.contract
    plan = replace(instantiation.plan, advisory=advisory)
    sizing = instantiation.sizing
    service_provenance = instantiation.service_provenance
    skipped = instantiation.skipped
    baseline_context = instantiation.baseline_context
    # A risk-driven run already opened with the sizing block, whose title
    # line states n and its provenance — no separate run-plan line.
    if emit and sizing.provenance != "risk-driven":
        print(
            render_run_plan(
                sizing.samples,
                sizing.provenance,
                demanded_by=sizing.demanded_by,
                threshold=sizing.threshold,
            )
        )
    if emit and contract.latency is not None and run_mode is RunKind.TEST:
        for line in render_latency_planning(plan_latency(contract.latency, plan.samples)):
            print(line)
    try:
        result = execute(
            contract,
            plan,
            on_sample=_tty_progress(declaration.service) if emit else None,
            # A measure run's baseline needs per-sample durations for its
            # latency block; test runs consume no per-sample observations.
            record_samples=run_mode is RunKind.MEASURE,
        )
    except ConfigurationRefusedError as refused:
        if verdict_dir is not None and run_mode is RunKind.TEST:
            write_refused_record(
                contract,
                plan,
                inputs_fingerprint(plan.inputs),
                refused,
                Path(verdict_dir),
                datetime.now(tz=UTC).isoformat(),
            )
        raise

    if verdict_dir is not None and run_mode is RunKind.TEST:
        design = _run_design(sizing_resolution, baseline_context, result)
        verdict_path = write_verdict_record(result, Path(verdict_dir), design)
        if emit:
            print(f"verdict record written: {verdict_path.as_posix()}\n")

    baseline_path: str | None = None
    if run_mode is RunKind.MEASURE:
        factor_record = {
            "taskFormat": FORMAT_IDENTIFIER,
            "runMode": run_mode.value,
            "taskFile": contract_path.name,
            # Roots disclosure: the declared value and the overridden
            # flag, never a resolved override path (publication hygiene).
            # Informational — baseline matching never consults these.
            **_roots_disclosure(declaration, services),
        }
        record = BaselineRecord.from_run_result(
            result,
            service_name=declaration.service,
            covariate_profile=dict(service_provenance),
            factor_record=factor_record,
            views=descriptive_view_fingerprints(declaration, registry),
        )
        baseline_path = str(write_baseline(record, Path(baseline_dir)))

    if emit:
        for name, reason in skipped:
            print(f"note: empirical criterion {name}: {reason}")
        print(render_run(result, baseline_path=baseline_path))
    return result


def _run_design(
    sizing_resolution: ResolvedSizing | None,
    baseline_context: BaselineContext | None,
    result: RunResult,
) -> RunDesign:
    """The recorded design facts a test's verdict record carries.

    The approach comes from the sizing conversation when one happened;
    otherwise it is the design fact the instantiation itself establishes —
    empirical criteria mean the size came first and the cutoff was derived
    at it (sample-size-first), declared bars alone are threshold-first. The
    baseline disclosure names the weakest regression criterion — the lowest
    baseline rate, the one downsizing hurts first — and its derived
    threshold ``c / n_t``.
    """
    approach = sizing_resolution.approach if sizing_resolution is not None else None
    if approach is None:
        approach = "sample-size-first" if baseline_context is not None else "threshold-first"
    claims: tuple[ClaimDisclosure, ...] = ()
    governing = None
    if sizing_resolution is not None and approach == RISK_DRIVEN_APPROACH:
        governing = sizing_resolution.governing
        claims = tuple(
            ClaimDisclosure(
                criterion=claim.criterion,
                baseline_rate=claim.baseline_rate,
                design_alternative_rate=claim.design_alternative_rate,
                confidence=claim.confidence,
                target_power=claim.target_power,
                required_n=claim.required_n,
            )
            for claim in sizing_resolution.claims
        )
    baseline = None
    regressions = [
        r.decision for r in result.criterion_results if isinstance(r.decision, RegressionVerdict)
    ]
    if baseline_context is not None and regressions:
        weakest = min(regressions, key=lambda d: d.baseline_successes / d.baseline_trials)
        baseline = BaselineDisclosure(
            source_file=baseline_context.source_file,
            generated_at=baseline_context.generated_at,
            samples=baseline_context.samples,
            baseline_rate=weakest.baseline_successes / weakest.baseline_trials,
            derived_threshold=weakest.derivation.threshold_real,
        )
    return RunDesign(approach=approach, claims=claims, governing=governing, baseline=baseline)


def _roots_disclosure(
    declaration: "ContractDeclaration", services: dict[str, "ServiceDefinition"]
) -> dict[str, str]:
    """Each file's declared roots as provenance entries.

    ``root.<name>`` carries the declared (file-relative) value;
    ``root.<name>.overridden`` states whether ``MAVAI_ROOT_<NAME>``
    replaced it. The contract file's and the services file's roots are
    disclosed under their own prefixes — per-file namespaces, per the
    format.
    """
    entries: dict[str, str] = {}
    for disclosure in getattr(declaration, "roots", ()):
        entries[f"root.{disclosure.name}"] = disclosure.declared
        entries[f"root.{disclosure.name}.overridden"] = str(disclosure.overridden).lower()
    definition = services.get(declaration.service)
    for disclosure in getattr(definition, "roots", ()) if definition is not None else ():
        entries[f"servicesRoot.{disclosure.name}"] = disclosure.declared
        entries[f"servicesRoot.{disclosure.name}.overridden"] = str(disclosure.overridden).lower()
    return entries
