"""The runner: load, instantiate, execute, render, persist."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.exploration import ExplorationRecord, exploration_stem, write_exploration
from baseltest.reporting import (
    render_explorations,
    render_html_report,
    render_run,
    render_run_plan,
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


def _tty_progress(label: str) -> "Callable[[int, int], None] | None":
    """A transient stderr progress line — only when stderr is a terminal.

    stdout stays clean for the run's actual output; non-interactive runs
    (pipes, CI) see nothing.
    """
    if not sys.stderr.isatty():
        return None

    def on_sample(completed: int, total: int) -> None:
        end = "\r" if completed < total else "\r\033[K"
        print(f"  sampling {label}: {completed}/{total}", end=end, file=sys.stderr, flush=True)

    return on_sample


def run(
    path: str | Path,
    mode: str | RunKind = RunKind.TEST,
    *,
    samples: int | None = None,
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
    result = execute(contract, plan, on_sample=_tty_progress(declaration.service) if emit else None)

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
        report_path = Path(html_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_html_report(result), encoding="utf-8")

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
        )
        record = ExplorationRecord.from_run_result(result, factors=configuration.factors)
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
