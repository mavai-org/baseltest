"""The runner: load, instantiate, execute, render, persist."""

from pathlib import Path

from baseltest.baseline import BaselineRecord, write_baseline
from baseltest.engine import RunKind, RunResult, execute
from baseltest.reporting import render_html_report, render_run

from ._errors import TaskConfigurationError
from ._instantiate import instantiate
from ._parser import FORMAT_IDENTIFIER, load_task
from ._services import discover_services

DEFAULT_BASELINE_DIR = Path("baselines")


def run(
    path: str | Path,
    *,
    baseline_dir: str | Path = DEFAULT_BASELINE_DIR,
    html_report: str | Path | None = None,
    emit: bool = True,
) -> RunResult:
    """Load and execute a task file; render its output; persist when measuring.

    Persistence strictly precedes rendering and any downstream assertion:
    under ``kind: measure`` the baseline artefact is on disk before this
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
    task_path = Path(path)
    declaration = load_task(task_path)
    services = discover_services(task_path)
    contract, plan, derived, service_provenance = instantiate(declaration, services)
    if html_report is not None and plan.kind is not RunKind.TEST:
        raise TaskConfigurationError(
            "the HTML report is the probabilistic-test summary and applies to test "
            "runs only — a measure run's product is its baseline artefact"
        )
    result = execute(contract, plan)

    baseline_path: str | None = None
    if plan.kind is RunKind.MEASURE:
        provenance = {
            "taskFormat": FORMAT_IDENTIFIER,
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
        print(render_run(result, baseline_path=baseline_path))
    return result
