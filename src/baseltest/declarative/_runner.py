"""The runner: load, instantiate, execute, render, persist."""

import sys
from collections.abc import Callable
from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.reporting import render_html_report, render_run

from ._errors import TaskConfigurationError
from ._instantiate import instantiate
from ._parser import FORMAT_IDENTIFIER, load_task
from ._registrations import discover_registrations
from ._services import discover_services

DEFAULT_BASELINE_DIR = Path("baselines")


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
    baseline_dir: str | Path = DEFAULT_BASELINE_DIR,
    html_report: str | Path | None = None,
    emit: bool = True,
) -> RunResult:
    """Load and execute a task file; render its output; persist when measuring.

    Persistence strictly precedes rendering and any downstream assertion:
    for a measure run the baseline artefact is on disk before this
    function returns.

    Args:
        path: The task file.
        baseline_dir: Where measure runs persist their baseline artefact.
        emit: Whether to print the rendered output (the CLI does; API
            callers may render from the returned result instead).

    Returns:
        The run result.

    Raises:
        TaskConfigurationError: The file (or its registrations) is not
            runnable as declared — refused before any invocation.
        InfeasibleRunError: The declared sample count cannot support every
            declared threshold under verification intent.
    """
    run_mode = RunKind(mode) if isinstance(mode, str) else mode
    task_path = Path(path)
    declaration = load_task(task_path)
    discover_registrations(task_path)
    services = discover_services(task_path)
    contract, plan, derived, service_provenance, skipped = instantiate(
        declaration, services, mode=run_mode
    )
    if html_report is not None and run_mode is not RunKind.TEST:
        raise TaskConfigurationError(
            "the HTML report is the probabilistic-test summary and applies to test "
            "runs only — a measure run's product is its baseline artefact"
        )
    result = execute(contract, plan, on_sample=_tty_progress(declaration.service) if emit else None)

    baseline_path: str | None = None
    if run_mode is RunKind.MEASURE:
        provenance = {
            "taskFormat": FORMAT_IDENTIFIER,
            "runMode": run_mode.value,
            "binding": declaration.service,
            "taskFile": task_path.name,
            **service_provenance,
        }
        record = BaselineRecord.from_run_result(result, provenance=provenance)
        baseline_path = str(write_baseline(record, Path(baseline_dir)))

    if html_report is not None:
        report_path = Path(html_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_html_report(result), encoding="utf-8")

    if emit:
        if derived is not None:
            print(
                f"samples not declared — derived {derived} (the smallest count "
                "supporting every declared threshold at its confidence)"
            )
        for name in skipped:
            print(
                f"note: criterion {name} declares no threshold and was not judged "
                "(`baseltest measure` records it)"
            )
        print(render_run(result, baseline_path=baseline_path))
    return result
