"""The runner: load, instantiate, execute, render, persist."""

import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import DefectDiagnosisError, RunKind, RunResult, execute, latency_block
from baseltest.exploration import ExplorationRecord, exploration_stem, write_exploration
from baseltest.optimization import (
    IterationCapture,
    OptimizationRecord,
    wire_scorer_name,
    write_optimization,
)
from baseltest.reporting import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    parse_verdict_record,
    read_verdict_directory,
    render_explorations,
    render_optimization_run,
    render_run,
    render_run_plan,
    render_test_report,
    render_verdict_record,
    write_verdict_record,
)

from ._disclosure import sizing_disclosure
from ._errors import ContractConfigurationError
from ._instantiate import (
    BaselineContext,
    _validate_inputs,
    descriptive_view_fingerprints,
    instantiate,
    instantiate_explore,
    instantiate_optimize_point,
    optimize_definition,
)
from ._optimize import OptimizationDeclaration
from ._parser import FORMAT_IDENTIFIER, ContractDeclaration, load_contract
from ._registrations import discover_registrations
from ._schema_walk import validate_declared_paths
from ._services import ServiceDefinition, discover_services
from ._services import _resolved_point as _configuration_identity
from ._sizing import ResolvedSizing
from ._steppers import (
    FailureDetail,
    FailureExemplar,
    IterationResult,
    IterationSummary,
    LatencySummary,
    OptimizeContext,
)

# Every baseltest-generated artefact lives under one visible parent in the
# working directory: one root entry, one .gitignore line, one `rm -rf` for a
# clean slate. The leading underscore keeps the directory from shadowing the
# installed package and carries the ecosystem's generated-output signal.
ARTEFACT_ROOT = Path("_baseltest")
DEFAULT_BASELINE_DIR = ARTEFACT_ROOT / "baselines"
DEFAULT_VERDICT_DIR = ARTEFACT_ROOT / "verdicts"
DEFAULT_EXPLORATIONS_DIR = ARTEFACT_ROOT / "explorations"
DEFAULT_OPTIMIZATIONS_DIR = ARTEFACT_ROOT / "optimizations"
DEFAULT_REPORTS_DIR = ARTEFACT_ROOT / "reports"

# The catalog's Optimize experiment default: sensible for typical LLM
# tuning scenarios, sized by --samples-per-iteration when deliberate.
DEFAULT_SAMPLES_PER_ITERATION = 20

# Rendering exploration comparisons is the shared family tool's job; this
# framework's half of that split is emitting the canonical artefacts. The
# pointer below is what any request for the old built-in renderer gets.
MAVAI_EXPLORE_POINTER = (
    "exploration comparison reports are rendered by the family's mavai tool: "
    "mavai explore <dir> [-o report.html] — public binaries: "
    "https://github.com/mavai-org/mavai/releases"
)


def _tty_progress(label: str) -> "Callable[[int, int], None] | None":
    """A stderr progress line — only when stderr is a terminal.

    The line overwrites itself while its run is sampling, then persists on
    completion: in a multi-configuration exploration each finished
    configuration leaves its line behind as a progress record instead of
    being erased by the next one. stdout stays clean for the run's actual
    output; non-interactive runs (pipes, CI) see nothing.
    """
    if not sys.stderr.isatty():
        return None

    def on_sample(completed: int, total: int) -> None:
        if completed < total:
            print(
                f"sampling {label}: {completed}/{total}",
                end="\r",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"\r\033[Ksampled {label}: {total}/{total}", file=sys.stderr)

    return on_sample


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
    declaration = load_contract(contract_path)
    discover_registrations(contract_path)
    services = discover_services(contract_path)
    contract, plan, sizing, service_provenance, skipped, baseline_context = instantiate(
        declaration,
        services,
        mode=run_mode,
        samples=samples,
        baseline_dir=Path(baseline_dir),
        samples_provenance=samples_provenance,
    )
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
            views=descriptive_view_fingerprints(declaration),
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


@dataclass(frozen=True, slots=True)
class ConfigurationExploration:
    """One explored configuration: its factors, its run result, its artefact."""

    factors: dict[str, object]
    result: RunResult
    path: Path


@dataclass(frozen=True, slots=True)
class AbortedConfiguration:
    """One configuration a defect stopped: its factors and the diagnosis.

    A defect is a bug in the testing machinery — not a countable outcome and
    not a sample. It stops *its* configuration with an actionable diagnosis
    instead of forfeiting the whole grid's paid spend; the remaining
    configurations run to completion.
    """

    factors: dict[str, object]
    diagnosis: str


@dataclass(frozen=True, slots=True)
class ExplorationRun:
    """An explore run's outcome: the configurations that completed, and any a
    defect contained.

    Iterating or indexing an ``ExplorationRun`` yields the *completed*
    configurations (baseline first), so the run reads as the sequence of
    artefacts it produced. ``aborted`` carries the configurations a defect
    stopped, each with its diagnosis: a partial run is a reported outcome,
    never a silent truncation.
    """

    completed: tuple[ConfigurationExploration, ...]
    aborted: tuple[AbortedConfiguration, ...] = ()

    def __iter__(self) -> "Iterator[ConfigurationExploration]":
        return iter(self.completed)

    def __len__(self) -> int:
        return len(self.completed)

    def __getitem__(self, index: int) -> ConfigurationExploration:
        return self.completed[index]


# mavai-ref: JVI-HGF78G* — do not remove (resolves in mavai-orchestrator)
def explore(
    path: str | Path,
    *,
    samples_per_config: int | None = None,
    explorations_dir: str | Path = DEFAULT_EXPLORATIONS_DIR,
    emit: bool = True,
) -> ExplorationRun:
    """Run the contract's inputs and criteria over every configuration in the grid.

    Per configuration this is a measure run in miniature — the same
    sampling loop, ``samples_per_config`` samples (default: a deliberately
    small count; triage is small by design) — with a descriptive posture:
    no thresholds are consulted, no verdict is rendered, and one
    exploration artefact per configuration is persisted. The core use is
    diffing two configurations' artefacts.

    Args:
        path: The contract file.
        samples_per_config: Samples per grid point; omitted, the small
            default applies.
        explorations_dir: The artefact directory; one subdirectory per
            contract, one file per configuration.
        emit: Whether to print the rendered summary.

    Returns:
        The run's outcome: the completed configurations (baseline first,
        iterable directly) and any a defect contained, each with its
        diagnosis.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation; in
            particular a service that resolves to a code-registered binding.
            A load-time refusal stops the whole run up front; only a runtime
            defect during a configuration's sampling is contained per
            configuration.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    discover_registrations(contract_path)
    services = discover_services(contract_path)
    configurations, sizing, notes = instantiate_explore(
        declaration, services, samples_per_config=samples_per_config
    )
    if emit:
        print(render_run_plan(sizing.samples, sizing.provenance, per_configuration=True))
        for note in notes:
            print(f"note: {note}")

    explored: list[ConfigurationExploration] = []
    aborted: list[AbortedConfiguration] = []
    for configuration in configurations:
        stem_source = tuple(configuration.factors.items())
        record_label = exploration_stem(stem_source)
        try:
            result = execute(
                configuration.contract,
                configuration.plan,
                on_sample=_tty_progress(record_label) if emit else None,
                record_samples=True,  # projections are the artefact's triage payload
            )
        except DefectDiagnosisError as defect:
            # Contain the defect to this configuration: its paid spend is
            # lost, but every remaining configuration's is not. Record the
            # diagnosis and carry on — the run reports the partial outcome.
            aborted.append(
                AbortedConfiguration(factors=dict(configuration.factors), diagnosis=str(defect))
            )
            if emit:
                print(f"note: configuration {record_label} aborted — {defect}", file=sys.stderr)
            continue
        record = ExplorationRecord.from_run_result(
            result,
            factors=configuration.factors,
            configuration=configuration.configuration,
        )
        artefact = write_exploration(record, Path(explorations_dir))
        explored.append(
            ConfigurationExploration(
                factors=dict(configuration.factors), result=result, path=artefact
            )
        )

    if emit:
        print(
            render_explorations(
                declaration.contract,
                sizing.samples,
                [(e.path.stem, e.result, e.path.as_posix()) for e in explored],
            )
        )
        for entry in aborted:
            label = exploration_stem(tuple(entry.factors.items()))
            print(f"  configuration {label} aborted with a defect (no artefact written)")
    return ExplorationRun(completed=tuple(explored), aborted=tuple(aborted))


@dataclass(frozen=True, slots=True)
class OptimizationOutcome:
    """One executed optimize run: its record and its artefact path.

    ``record`` and ``path`` are ``None`` only when a defect stopped the run
    before its first iteration produced a scored data point — there is then
    no history to persist. ``defect`` carries the diagnosis when a defect
    stopped the search (whether or not any iteration completed first).
    """

    run_id: str
    record: OptimizationRecord | None
    path: Path | None
    defect: str | None = None


# mavai-ref: JVI-PS5XC2C — do not remove (resolves in mavai-orchestrator)
def optimize(
    path: str | Path,
    *,
    run_id: str | None = None,
    all_entries: bool = False,
    samples_per_iteration: int | None = None,
    optimizations_dir: str | Path = DEFAULT_OPTIMIZATIONS_DIR,
    emit: bool = True,
) -> tuple[OptimizationOutcome, ...]:
    """Run the contract's Optimize experiments: iterate, score, persist the history.

    Per selected ``optimizations:`` entry this drives the settled loop:
    iteration 0 is the baseline configuration with the entry's ``initial:``
    overlay applied; each subsequent iteration's configuration is the
    stepper's proposal over the whole current configuration. Every
    iteration is a measure run in miniature with the explore verb's
    descriptive posture — no thresholds consulted, no verdict rendered —
    scored by the entry's scorer, with best-tracking in the entry's
    objective direction. The run stops at the iteration cap, on the
    plateau window, or when the stepper stops; one artefact per run
    records the full history.

    Args:
        path: The contract file.
        run_id: The single entry to run. With several entries declared and
            neither this nor ``all_entries``, the selection is refused —
            never guessed.
        all_entries: Run every declared entry.
        samples_per_iteration: Samples per iteration; omitted, the
            catalog's default applies.
        optimizations_dir: The artefact directory; one subdirectory per
            contract, one file per run id.
        emit: Whether to print the rendered summary.

    Returns:
        One outcome per executed run, in declaration order.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared, the selection is ambiguous, or a stepper
            mid-run returns a configuration the service type refuses.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    discover_registrations(contract_path)
    services = discover_services(contract_path)
    definition = optimize_definition(declaration, services)
    entries = _select_entries(definition, run_id, all_entries)
    samples = (
        samples_per_iteration
        if samples_per_iteration is not None
        else DEFAULT_SAMPLES_PER_ITERATION
    )
    if emit:
        provenance = "explicit" if samples_per_iteration is not None else "default"
        print(render_run_plan(samples, provenance, per_iteration=True))

    outcomes: list[OptimizationOutcome] = []
    for entry in entries:
        if emit:
            for note in entry.notes:
                print(f"note: {note}")
        outcomes.append(
            _drive_optimization(
                declaration, definition, entry, samples, Path(optimizations_dir), emit
            )
        )
    return tuple(outcomes)


def _drive_optimization(
    declaration: ContractDeclaration,
    definition: ServiceDefinition,
    entry: OptimizationDeclaration,
    samples: int,
    optimizations_dir: Path,
    emit: bool,
) -> OptimizationOutcome:
    """One entry's full loop: iterate, score, track the best, persist.

    A defect (a non-``TransformError`` exception escaping a transform or
    postcondition) that escapes an iteration's sampling cannot yield a score
    — a defected iteration is not a data point. It is contained here: the
    search stops with a ``defect`` termination, the defected iteration is
    *not* appended to the history (recording it as a scored iteration would
    be dishonest), and the best is selected among the iterations that did
    complete. This keeps the defect from forfeiting the whole entry's paid
    spend and, under ``--all``, keeps it from killing sibling entries — an
    entry whose very first iteration defects yields no persistable history,
    so it returns an aborted outcome with no artefact rather than an empty
    one.
    """
    history: list[IterationResult] = []
    captures: list[IterationCapture] = []
    best: IterationResult | None = None
    best_index = 0
    plateau = 0
    termination = "max-iterations"
    defect_diagnosis: str | None = None
    parameters = entry.parameters
    visited: set[tuple[Any, ...]] = set()
    for index in range(entry.max_iterations):
        visited.add(_configuration_identity(definition.type, parameters))
        point = instantiate_optimize_point(declaration, definition, parameters, samples)
        label = f"{entry.run_id} iteration {index}"
        try:
            result = execute(
                point.contract,
                point.plan,
                on_sample=_tty_progress(label) if emit else None,
                record_samples=True,  # projections and exemplars are the payload
            )
        except DefectDiagnosisError as defect:
            defect_diagnosis = str(defect)
            termination = "defect"
            if emit:
                print(f"note: {label} aborted — {defect}", file=sys.stderr)
            break
        summary = _iteration_summary(result)
        score = float(entry.score(summary))
        iteration_result = IterationResult(
            config=dict(point.configuration), score=score, summary=summary
        )
        history.append(iteration_result)
        captures.append(IterationCapture.from_run_result(index, result, point.configuration, score))
        if best is None or _improved(score, best.score, entry.objective):
            best = iteration_result
            best_index = index
            plateau = 0
        else:
            plateau += 1
            if entry.no_improvement_window is not None and plateau >= entry.no_improvement_window:
                termination = "no-improvement-window"
                break
        if index + 1 == entry.max_iterations:
            break  # the cap is reached; no next configuration to propose
        context = OptimizeContext(
            history=tuple(history),
            best=best,
            iteration=index + 1,
            iterations_remaining=entry.max_iterations - (index + 1),
        )
        next_parameters = _next_parameters(
            entry, definition, context, iteration_result.config, index + 1
        )
        if next_parameters is None:
            termination = "stepper-stopped"
            break
        if emit and _configuration_identity(definition.type, next_parameters) in visited:
            # Deliberate, not a defect: under a stochastic service a single
            # visit's score is noisy, and repeated visits pool into
            # stronger evidence — say so instead of looking stuck.
            print(
                f"note: iteration {index + 1} re-measures a configuration this run "
                "has already visited — repeated measurements accumulate evidence "
                "against the noise in any single visit"
            )
        parameters = next_parameters

    if not captures:
        # A defect stopped the search before any iteration produced a scored
        # data point: there is no history to persist. Report the aborted
        # entry (no artefact) and let sibling entries run.
        if emit:
            print(
                f"note: optimization {entry.run_id!r} produced no scored iteration "
                "— aborted by a defect before iteration 0 completed; no artefact written",
                file=sys.stderr,
            )
        return OptimizationOutcome(
            run_id=entry.run_id, record=None, path=None, defect=defect_diagnosis
        )

    record = OptimizationRecord(
        contract_id=declaration.contract,
        experiment_id=entry.run_id,
        objective=entry.objective,
        scorer=wire_scorer_name(entry.scorer_name),
        generated_at=captures[-1].observation.generated_at,
        iterations=tuple(captures),
        best_index=best_index,
        termination=termination,
        stepper=_stepper_block(entry),
    )
    artefact = write_optimization(record, optimizations_dir)
    if emit:
        print(
            render_optimization_run(
                declaration.contract,
                entry.run_id,
                samples,
                [
                    (c.index, c.score, c.observation.successes, c.observation.samples_executed)
                    for c in captures
                ],
                termination,
                best_index,
                dict(record.best.factors),
                artefact.as_posix(),
            )
        )
    return OptimizationOutcome(
        run_id=entry.run_id, record=record, path=artefact, defect=defect_diagnosis
    )


def _iteration_summary(result: RunResult) -> IterationSummary:
    """One iteration's aggregate, in the shape scorers and steppers consume."""
    exemplars: dict[str, list[FailureExemplar]] = {}
    for sample in result.samples:
        for name, reason in sample.failure_reasons:
            exemplars.setdefault(name, []).append(
                FailureExemplar(input=result.plan.inputs[sample.input_index], reason=reason)
            )
    failures: dict[str, FailureDetail] = {}
    for criterion_result in result.criterion_results:
        tally = criterion_result.tally
        failed = tally.trials - tally.successes
        if failed:
            failures[criterion_result.name] = FailureDetail(
                count=failed, exemplars=tuple(exemplars.get(criterion_result.name, ()))
            )
    block = latency_block(result.samples)
    latency = None
    if block is not None:
        stated = dict(block.percentiles)
        latency = LatencySummary(
            contributing_samples=block.contributing_samples,
            total_samples=block.total_samples,
            p50_ms=stated.get("p50Ms"),
            p90_ms=stated.get("p90Ms"),
            p95_ms=stated.get("p95Ms"),
            p99_ms=stated.get("p99Ms"),
        )
    return IterationSummary(
        passes=result.overall_successes,
        samples=result.plan.samples,
        failures_by_criterion=failures,
        latency=latency,
    )


def _select_entries(
    definition: ServiceDefinition, run_id: str | None, all_entries: bool
) -> tuple[OptimizationDeclaration, ...]:
    """The entries this invocation runs — never guessed when there are several."""
    entries = definition.optimizations
    if run_id is not None:
        for entry in entries:
            if entry.run_id == run_id:
                return (entry,)
        available = ", ".join(entry.run_id for entry in entries)
        raise ContractConfigurationError(
            f"service {definition.name!r} declares no optimization with id {run_id!r} "
            f"— declared: {available}"
        )
    if all_entries or len(entries) == 1:
        return entries
    available = ", ".join(entry.run_id for entry in entries)
    raise ContractConfigurationError(
        f"service {definition.name!r} declares {len(entries)} optimizations — name "
        f"the one to run ({available}), or pass --all to run every entry (each is "
        "an independent, potentially expensive experiment)"
    )


def _improved(score: float, best: float, objective: str) -> bool:
    return score > best if objective == "maximize" else score < best


def _stepper_block(entry: OptimizationDeclaration) -> tuple[tuple[str, object], ...]:
    """The artefact's mutator-provenance block: name, config, runtime residue."""
    block: list[tuple[str, object]] = [("name", entry.stepper_name)]
    block.extend((key.replace("_", "-"), value) for key, value in entry.stepper_config.items())
    runtime = getattr(entry.step, "provenance", None)
    if isinstance(runtime, dict):
        block.extend(sorted(runtime.items()))
    return tuple(block)


def _next_parameters(
    entry: OptimizationDeclaration,
    definition: ServiceDefinition,
    context: OptimizeContext,
    configuration: dict[str, Any],
    iteration: int,
) -> Any | None:
    """One stepper call, its proposal validated into the next parameters.

    Returns ``None`` when the stepper stopped the search. Any
    configuration the service type accepts is a legitimate proposal —
    including one this run has already measured: a stochastic score is
    noisy, and re-measuring a configuration pools into stronger evidence
    (the caller notes a revisit on the console rather than refusing it).

    Raises:
        ContractConfigurationError: The proposal is not a configuration
            mapping, or does not fit the service type.
    """
    where = (
        f"optimization {entry.run_id!r}: iteration {iteration} configuration "
        f"(from stepper {entry.stepper_name!r})"
    )
    proposal = entry.step(dict(configuration), context)
    if proposal is None:
        return None
    if not isinstance(proposal, dict):
        raise ContractConfigurationError(
            f"{where}: the stepper returned {type(proposal).__name__}, not a "
            "configuration mapping — a stepper returns the whole next "
            "configuration, or None to stop"
        )
    return definition.type.parse(definition.name, proposal, where)


def check(path: str | Path) -> tuple[str, ...]:
    """Validate a contract against its services and bindings — zero samples.

    The authoring loop's compile step: loads the contract, discovers the
    services file and the bindings, and runs every load-time join — the
    configuration ↔ factory-signature joins (at services load), the
    service reference's resolution, and the inputs ↔ per-sample-callable
    join — constructing the per-sample callable exactly as a run would,
    for the baseline and for every exploration grid point, without
    invoking anything. A missing baseline is not checked: absence is a
    run-time fact, not a configuration defect.

    Returns one line per validated fact. Raises on the first join that
    fails, with the same refusal a run would give.

    Raises:
        ContractConfigurationError: The first failing join.
    """
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    discover_registrations(contract_path)
    services = discover_services(contract_path)
    # The baseline path, validated by the machinery a real run uses —
    # check and run cannot drift apart.
    instantiate(declaration, services, mode=RunKind.MEASURE, samples=1)
    facts = [
        f"contract {declaration.contract!r}: {len(declaration.criteria)} criteria, "
        f"{len(declaration.inputs)} inputs"
    ]
    definition = services.get(declaration.service)
    if definition is None:
        facts.append(
            f"service {declaration.service!r}: binding resolved, every input joined "
            "against its signature"
        )
        facts.extend(validate_declared_paths(declaration, None, declaration.service))
        return tuple(facts)
    facts.append(
        f"service {declaration.service!r}: type {definition.type.name!r}, baseline "
        "configuration valid"
    )
    facts.extend(
        validate_declared_paths(
            declaration,
            getattr(definition.configuration, "response_schema", None),
            declaration.service,
        )
    )
    for parameters in definition.explorations:
        point, _note = definition.type.prepare_explore_point(parameters)
        _validate_inputs(declaration.service, definition.type.invoker(point), declaration.inputs)
    if definition.explorations:
        count = len(definition.explorations)
        entries = "entry" if count == 1 else "entries"
        facts.append(f"exploration grid: {count} {entries} constructed and joined")
    for entry in definition.optimizations:
        _validate_inputs(
            declaration.service, definition.type.invoker(entry.parameters), declaration.inputs
        )
    if definition.optimizations:
        count = len(definition.optimizations)
        entries = "entry" if count == 1 else "entries"
        facts.append(
            f"optimizations: {count} {entries} validated — steppers constructed, iteration 0 joined"
        )
        # An inert plateau window is a configuration fact worth stating,
        # though not a refusal: the run simply goes to its cap.
        facts.extend(note for entry in definition.optimizations for note in entry.notes)
    return tuple(facts)


def report(
    kind: str,
    *,
    verdict_dir: str | Path = DEFAULT_VERDICT_DIR,
    out: str | Path | None = None,
) -> Path:
    """Render an HTML report from persisted artefacts — never executes anything.

    ``test`` sweeps the verdict records; ``explore`` is the family tool's
    job (the refusal names it); ``measure`` is reserved (the family has no
    measure report type yet). Exit semantics are the caller's: this
    function raises a refusal when there is nothing to render.

    Raises:
        ContractConfigurationError: Nothing to render — missing or empty
            artefact directory, or a report kind this framework does not
            render.
    """
    if kind == "measure":
        raise ContractConfigurationError(
            "no measure report type exists yet in the mavai family — a measure "
            "run's product is its baseline artefact. Render `basel report test` "
            "instead."
        )
    if kind == "explore":
        raise ContractConfigurationError(MAVAI_EXPLORE_POINTER)
    directory = Path(verdict_dir)
    sweep = read_verdict_directory(directory) if directory.is_dir() else None
    if sweep is None or not sweep.records:
        raise ContractConfigurationError(
            f"no verdict records found under {directory.as_posix()} — run "
            "`basel test <contract>` first, then render the report"
        )
    for name in sweep.skipped:
        print(f"note: skipped unparseable verdict record {name}", file=sys.stderr)
    records = list(sweep.records)
    content = render_test_report(records, [sizing_disclosure(r) for r in records])
    target = Path(out) if out is not None else DEFAULT_REPORTS_DIR / "test.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
