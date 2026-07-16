"""The runner: load, instantiate, execute, render, persist."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.exploration import ExplorationRecord, exploration_stem, write_exploration
from baseltest.reporting import (
    RISK_DRIVEN_APPROACH,
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    parse_verdict_record,
    read_verdict_directory,
    render_explorations,
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
    instantiate,
    instantiate_explore,
)
from ._parser import FORMAT_IDENTIFIER, load_contract
from ._registrations import discover_registrations
from ._services import discover_services
from ._sizing import ResolvedSizing

# Every baseltest-generated artefact lives under one visible parent in the
# working directory: one root entry, one .gitignore line, one `rm -rf` for a
# clean slate. The leading underscore keeps the directory from shadowing the
# installed package and carries the ecosystem's generated-output signal.
ARTEFACT_ROOT = Path("_baseltest")
DEFAULT_BASELINE_DIR = ARTEFACT_ROOT / "baselines"
DEFAULT_VERDICT_DIR = ARTEFACT_ROOT / "verdicts"
DEFAULT_EXPLORATIONS_DIR = ARTEFACT_ROOT / "explorations"
DEFAULT_REPORTS_DIR = ARTEFACT_ROOT / "reports"

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
        record = BaselineRecord.from_run_result(result, provenance=provenance)
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


# javai-ref: JVI-HGF78G* — do not remove (resolves in javai-orchestrator)
def explore(
    path: str | Path,
    *,
    samples_per_config: int | None = None,
    explorations_dir: str | Path = DEFAULT_EXPLORATIONS_DIR,
    emit: bool = True,
) -> tuple[ConfigurationExploration, ...]:
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
        One entry per configuration, baseline first.

    Raises:
        ContractConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation; in
            particular a service that resolves to a code-registered binding.
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
    for configuration in configurations:
        stem_source = tuple(configuration.factors.items())
        record_label = exploration_stem(stem_source)
        result = execute(
            configuration.contract,
            configuration.plan,
            on_sample=_tty_progress(record_label) if emit else None,
            record_samples=True,  # projections are the artefact's triage payload
        )
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
    return tuple(explored)


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
        return tuple(facts)
    facts.append(
        f"service {declaration.service!r}: type {definition.type.name!r}, baseline "
        "configuration valid"
    )
    for parameters in definition.explorations:
        point, _note = definition.type.prepare_explore_point(parameters)
        _validate_inputs(declaration.service, definition.type.invoker(point), declaration.inputs)
    if definition.explorations:
        count = len(definition.explorations)
        entries = "entry" if count == 1 else "entries"
        facts.append(f"exploration grid: {count} {entries} constructed and joined")
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
