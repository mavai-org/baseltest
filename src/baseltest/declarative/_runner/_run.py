"""The ``test``/``measure`` verb: load, instantiate, execute, render, persist.

Persistence strictly precedes rendering and any downstream assertion: for a
measure run the baseline artefact is on disk before ``run`` returns.
"""

from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.reporting import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    parse_verdict_record,
    render_run,
    render_run_plan,
    render_test_report,
    render_verdict_record,
    write_verdict_record,
)

from .._disclosure import sizing_disclosure
from .._errors import ContractConfigurationError
from .._instantiate import BaselineContext, descriptive_view_fingerprints, instantiate
from .._parser import FORMAT_IDENTIFIER
from .._registry import Bindings
from .._sizing import ResolvedSizing
from ._load import LoadedContract, load_for_run
from ._shared import DEFAULT_BASELINE_DIR, _tty_progress


def run(
    path: str | Path,
    mode: str | RunKind = RunKind.TEST,
    *,
    samples: int | None = None,
    samples_provenance: str | None = None,
    sizing_resolution: ResolvedSizing | None = None,
    baseline_dir: str | Path = DEFAULT_BASELINE_DIR,
    verdict_dir: str | Path | None = None,
    html_report: str | Path | None = None,
    emit: bool = True,
    bindings: Bindings | None = None,
    loaded: LoadedContract | None = None,
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

    Returns:
        The run result.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation.
        InfeasibleRunError: The declared sample count cannot support every
            declared threshold under verification intent.
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
    )
    contract = instantiation.contract
    plan = instantiation.plan
    sizing = instantiation.sizing
    service_provenance = instantiation.service_provenance
    skipped = instantiation.skipped
    baseline_context = instantiation.baseline_context
    design = None
    if run_mode is RunKind.TEST:
        design = _run_design(sizing_resolution, baseline_context)
    if html_report is not None and run_mode is not RunKind.TEST:
        raise ContractConfigurationError(
            "the HTML report is the probabilistic-test summary and applies to test "
            "runs only — a measure run's product is its baseline artefact"
        )
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
    result = execute(
        contract,
        plan,
        on_sample=_tty_progress(declaration.service) if emit else None,
        # A measure run's baseline needs per-sample durations for its
        # latency block; test runs consume no per-sample observations.
        record_samples=run_mode is RunKind.MEASURE,
    )

    if verdict_dir is not None and run_mode is RunKind.TEST:
        verdict_path = write_verdict_record(result, Path(verdict_dir), design)
        if emit:
            print(f"verdict record written: {verdict_path.as_posix()}\n")

    baseline_path: str | None = None
    if run_mode is RunKind.MEASURE:
        provenance = {
            "taskFormat": FORMAT_IDENTIFIER,
            "runMode": run_mode.value,
            "binding": declaration.service,
            "taskFile": contract_path.name,
            **service_provenance,
        }
        record = BaselineRecord.from_run_result(
            result,
            provenance=provenance,
            views=descriptive_view_fingerprints(declaration, registry),
        )
        baseline_path = str(write_baseline(record, Path(baseline_dir)))

    if html_report is not None:
        # The one rendering path: the report is rendered from the persisted
        # verdict record's content, so an inline report and a post-hoc
        # `basel report test` over the same run are identical.
        verdict_record = parse_verdict_record(render_verdict_record(result, design))
        report_path = Path(html_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_test_report([verdict_record], [sizing_disclosure(verdict_record)]),
            encoding="utf-8",
        )

    if emit:
        for name, reason in skipped:
            print(f"note: empirical criterion {name}: {reason}")
        print(render_run(result, baseline_path=baseline_path))
    return result


def _run_design(
    sizing_resolution: ResolvedSizing | None,
    baseline_context: BaselineContext | None,
) -> RunDesign:
    """The recorded design facts a test's verdict record carries.

    The approach comes from the sizing conversation when one happened;
    otherwise it is the design fact the instantiation itself establishes —
    empirical criteria mean the size came first and the bar was derived at
    it (sample-size-first), declared bars alone are threshold-first.
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
                tolerated_rate=claim.tolerated_rate,
                confidence=claim.confidence,
                target_power=claim.target_power,
                required_n=claim.required_n,
            )
            for claim in sizing_resolution.claims
        )
    baseline = None
    if baseline_context is not None:
        baseline = BaselineDisclosure(
            source_file=baseline_context.source_file,
            generated_at=baseline_context.generated_at,
            samples=baseline_context.samples,
            baseline_rate=baseline_context.weakest_effective_rate,
            derived_threshold=baseline_context.weakest_threshold,
        )
    return RunDesign(approach=approach, claims=claims, governing=governing, baseline=baseline)
