"""The ``baseltest`` console script."""

import argparse
import sys
from pathlib import Path

from baseltest.engine import InfeasibleRunError, Verdict
from baseltest.reporting import render_infeasible

from ._errors import TaskConfigurationError
from ._runner import DEFAULT_BASELINE_DIR, run


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``baseltest test task.yaml`` / ``baseltest measure task.yaml``."""
    parser = argparse.ArgumentParser(
        prog="baseltest",
        description="Statistically honest testing for stochastic services.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for verb, description in (
        ("test", "judge the task's thresholded criteria: a probabilistic test"),
        ("measure", "record every criterion and persist the baseline artefact"),
    ):
        verb_parser = subparsers.add_parser(verb, help=description)
        verb_parser.add_argument("task_file", type=Path, help="path to the task file")
        verb_parser.add_argument(
            "--baseline-dir",
            type=Path,
            default=DEFAULT_BASELINE_DIR,
            help="directory measure runs persist baselines into",
        )
        verb_parser.add_argument(
            "--html-report",
            type=Path,
            default=None,
            help="write the probabilistic-test summary to this path (test only)",
        )
    arguments = parser.parse_args(argv)

    try:
        result = run(
            arguments.task_file,
            mode=arguments.command,
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
