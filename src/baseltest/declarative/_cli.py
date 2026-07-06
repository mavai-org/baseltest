"""The ``baseltest`` console script."""

import argparse
import sys
from pathlib import Path

from baseltest.engine import InfeasibleRunError, Verdict
from baseltest.reporting import render_infeasible

from ._errors import TaskConfigurationError
from ._runner import DEFAULT_BASELINE_DIR, run


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``baseltest run task.yaml``."""
    parser = argparse.ArgumentParser(
        prog="baseltest",
        description="Statistically honest testing for stochastic services.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run a mavai task file")
    run_parser.add_argument("task_file", type=Path, help="path to the task file")
    run_parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_BASELINE_DIR,
        help="directory measure runs persist baselines into",
    )
    run_parser.add_argument(
        "--html-report",
        type=Path,
        default=None,
        help="write the self-contained probabilistic-test summary to this path (test runs only)",
    )
    arguments = parser.parse_args(argv)

    try:
        result = run(
            arguments.task_file,
            baseline_dir=arguments.baseline_dir,
            html_report=arguments.html_report,
        )
    except TaskConfigurationError as refusal:
        print(f"task {arguments.task_file}: cannot run as declared", file=sys.stderr)
        print(f"  {refusal}", file=sys.stderr)
        return 2
    except InfeasibleRunError as infeasible:
        print(render_infeasible(arguments.task_file.stem, infeasible), file=sys.stderr)
        return 2
    if result.composite is Verdict.FAIL:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
