"""The runner: load, instantiate, execute, render, persist."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.exploration import ExplorationRecord, exploration_stem, write_exploration
from baseltest.reporting import (
    parse_verdict_record,
    read_exploration_directory,
    read_verdict_directory,
    render_exploration_report,
    render_explorations,
    render_run,
    render_run_plan,
    render_test_report,
    render_verdict_record,
    write_verdict_record,
)

from ._errors import ContractConfigurationError
from ._instantiate import instantiate, instantiate_explore
from ._parser import FORMAT_IDENTIFIER, load_contract
from ._registrations import discover_registrations
from ._services import discover_services

# Every baseltest-generated artefact lives under one visible parent in the
# working directory: one root entry, one .gitignore line, one `rm -rf` for a
# clean slate. The leading underscore keeps the directory from shadowing the
# installed package and carries the ecosystem's generated-output signal.
ARTEFACT_ROOT = Path("_baseltest")
DEFAULT_BASELINE_DIR = ARTEFACT_ROOT / "baselines"
DEFAULT_VERDICT_DIR = ARTEFACT_ROOT / "verdicts"
DEFAULT_EXPLORATIONS_DIR = ARTEFACT_ROOT / "explorations"
DEFAULT_REPORTS_DIR = ARTEFACT_ROOT / "reports"


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
                f"  sampling {label}: {completed}/{total}",
                end="\r",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"\r\033[K  sampled {label}: {total}/{total}", file=sys.stderr)

    return on_sample


def run(
    path: str | Path,
    mode: str | RunKind = RunKind.TEST,
    *,
    samples: int | None = None,
    samples_provenance: str | None = None,
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
    contract_path = Path(path)
    declaration = load_contract(contract_path)
    discover_registrations(contract_path)
    services = discover_services(contract_path)
    contract, plan, sizing, service_provenance, skipped = instantiate(
        declaration,
        services,
        mode=run_mode,
        samples=samples,
        baseline_dir=Path(baseline_dir),
        samples_provenance=samples_provenance,
    )
    if html_report is not None and run_mode is not RunKind.TEST:
        raise ContractConfigurationError(
            "the HTML report is the probabilistic-test summary and applies to test "
            "runs only — a measure run's product is its baseline artefact"
        )
    if emit:
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
        verdict_path = write_verdict_record(result, Path(verdict_dir))
        if emit:
            print(f"  verdict record written: {verdict_path.as_posix()}")

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
        verdict_record = parse_verdict_record(render_verdict_record(result))
        report_path = Path(html_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_test_report([verdict_record]), encoding="utf-8")

    if emit:
        for name, reason in skipped:
            print(f"note: empirical criterion {name}: {reason}")
        print(render_run(result, baseline_path=baseline_path))
    return result


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
    html_report: str | Path | None = None,
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
        html_report: When given, the comparison report is rendered from the
            just-persisted artefacts to this path — the same renderer
            `basel report explore` uses, so the two are identical.
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

    if html_report is not None:
        # The one rendering path: parse the just-persisted artefacts back,
        # scoped to this contract, and render with the report verb's renderer.
        sweep = read_exploration_directory(Path(explorations_dir))
        contracts = [c for c in sweep.contracts if c.contract_id == declaration.contract]
        report_path = Path(html_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_exploration_report(contracts), encoding="utf-8")

    if emit:
        print(
            render_explorations(
                declaration.contract,
                sizing.samples,
                [(e.path.stem, e.result, e.path.as_posix()) for e in explored],
            )
        )
    return tuple(explored)


def report(
    kind: str,
    *,
    verdict_dir: str | Path = DEFAULT_VERDICT_DIR,
    explorations_dir: str | Path = DEFAULT_EXPLORATIONS_DIR,
    out: str | Path | None = None,
) -> Path:
    """Render an HTML report from persisted artefacts — never executes anything.

    ``test`` sweeps the verdict records; ``explore`` sweeps the exploration
    artefacts; ``measure`` is reserved (the family has no measure report
    type yet). Exit semantics are the caller's: this function raises a
    refusal when there is nothing to render.

    Raises:
        ContractConfigurationError: Nothing to render — missing or empty
            artefact directory, or a report kind that does not exist yet.
    """
    if kind == "measure":
        raise ContractConfigurationError(
            "no measure report type exists yet in the mavai family — a measure "
            "run's product is its baseline artefact. Render `basel report test` "
            "or `basel report explore` instead."
        )
    if kind == "test":
        directory = Path(verdict_dir)
        sweep = read_verdict_directory(directory) if directory.is_dir() else None
        if sweep is None or not sweep.records:
            raise ContractConfigurationError(
                f"no verdict records found under {directory.as_posix()} — run "
                "`basel test <contract>` first, then render the report"
            )
        for name in sweep.skipped:
            print(f"note: skipped unparseable verdict record {name}", file=sys.stderr)
        content = render_test_report(list(sweep.records))
        target = Path(out) if out is not None else DEFAULT_REPORTS_DIR / "test.html"
    else:
        root = Path(explorations_dir)
        exploration_sweep = read_exploration_directory(root) if root.is_dir() else None
        if exploration_sweep is None or not exploration_sweep.contracts:
            raise ContractConfigurationError(
                f"no exploration artefacts found under {root.as_posix()} — run "
                "`basel explore <contract>` first, then render the report"
            )
        for name in exploration_sweep.skipped:
            print(f"note: skipped unparseable exploration artefact {name}", file=sys.stderr)
        content = render_exploration_report(list(exploration_sweep.contracts))
        target = Path(out) if out is not None else DEFAULT_REPORTS_DIR / "explorations.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
