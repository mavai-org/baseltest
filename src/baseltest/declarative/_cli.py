"""The ``basel`` console script — the `baseltest` package's command."""

import argparse
import sys
from pathlib import Path

from baseltest.engine import InfeasibleRunError, RunResult, Verdict
from baseltest.reporting import bar_standing, render_infeasible

from ._errors import ContractConfigurationError
from ._parser import load_contract
from ._providers import ProviderResponseError
from ._registrations import discover_registrations
from ._runner import (
    DEFAULT_BASELINE_DIR,
    DEFAULT_EXPLORATIONS_DIR,
    DEFAULT_VERDICT_DIR,
    explore,
    report,
    run,
)
from ._services import discover_services
from ._sizing import ResolvedSizing, SizingRefusalError, resolve_test_sizing


def main(argv: list[str] | None = None) -> int:
    """Entry point: the ``test`` / ``measure`` / ``explore`` verbs over a contract file."""
    parser = argparse.ArgumentParser(
        prog="basel",
        description="Statistically honest testing for stochastic services.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for verb, description in (
        ("test", "judge the contract's thresholded criteria: a probabilistic test"),
        ("measure", "record every criterion and persist the baseline artefact"),
    ):
        verb_parser = subparsers.add_parser(verb, help=description)
        verb_parser.add_argument("contract_file", type=Path, help="path to the contract file")
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
        verb_parser.add_argument(
            "--samples",
            type=int,
            default=None,
            help=(
                "run with this many samples instead of the file's -- a cheaper run; "
                "bounds and recorded standings are honestly computed at this size "
                "(a test is refused if it cannot support the declared bars)"
            ),
        )
        if verb == "test":
            verb_parser.add_argument(
                "--verdict-dir",
                type=Path,
                default=DEFAULT_VERDICT_DIR,
                help="directory for the canonical verdict-record XML (family schema)",
            )
            verb_parser.add_argument(
                "--no-verdict-xml",
                action="store_true",
                help="do not write the verdict-record XML",
            )
            verb_parser.add_argument(
                "--tolerate",
                action="append",
                metavar="RATE|CRITERION=RATE",
                help=(
                    "the lowest real pass rate you are willing to accept before the "
                    "test should fail (a rate like 0.84, or a percentage like 84); "
                    "the run size is computed from it. The bare form addresses a "
                    "contract with exactly one empirical criterion; repeat "
                    "CRITERION=RATE to address several"
                ),
            )
            verb_parser.add_argument(
                "--confidence",
                default=None,
                help=(
                    "how sure you want to be that a PASS is trustworthy (0.95 or "
                    "95); overrides the contract file's declared confidence"
                ),
            )
            verb_parser.add_argument(
                "--power",
                default=None,
                help=(
                    "advanced: how reliably a genuine drop to the tolerated rate "
                    "must be caught (default 0.8)"
                ),
            )
            verb_parser.add_argument(
                "--yes",
                action="store_true",
                help="skip confirmation prompts (for automation)",
            )
            verb_parser.add_argument(
                "--json",
                dest="emit_json",
                action="store_true",
                help="machine-readable sizing output; implies non-interactive",
            )
            verb_parser.add_argument(
                "--force",
                action="store_true",
                help=(
                    "design the test anyway when the tolerance is at or above the "
                    "proven baseline (requires --samples; the required-size search "
                    "is undefined in that regime)"
                ),
            )
        if verb == "measure":
            verb_parser.add_argument(
                "--assert",
                dest="assert_bars",
                action="store_true",
                help=(
                    "after recording (the baseline is persisted regardless), fail "
                    "the run if a declared bar was not met (exit 1); a judgement "
                    "the sample size cannot support exits 3"
                ),
            )
    explore_parser = subparsers.add_parser(
        "explore",
        help=(
            "run every configuration in the service's grid and persist one "
            "descriptive artefact per configuration — triage, not judgement"
        ),
    )
    explore_parser.add_argument("contract_file", type=Path, help="path to the contract file")
    explore_parser.add_argument(
        "--samples-per-config",
        type=int,
        default=None,
        help=(
            "samples per grid configuration (default: 5 — an exploration is "
            "triage, and small counts are the point; no count is ever refused "
            "as too small)"
        ),
    )
    explore_parser.add_argument(
        "--explorations-dir",
        type=Path,
        default=DEFAULT_EXPLORATIONS_DIR,
        help="directory exploration artefacts are written into (one file per configuration)",
    )
    explore_parser.add_argument(
        "--html-report",
        type=Path,
        default=None,
        help="also render the exploration comparison report to this path",
    )
    report_parser = subparsers.add_parser(
        "report",
        help=("render an HTML report from persisted artefacts — post-hoc, never invokes a service"),
    )
    report_parser.add_argument(
        "kind",
        choices=("test", "measure", "explore"),
        help=(
            "which report to render: test (from verdict records) or explore "
            "(from exploration artefacts); measure is reserved"
        ),
    )
    report_parser.add_argument(
        "--verdict-dir",
        type=Path,
        default=DEFAULT_VERDICT_DIR,
        help="where `report test` reads verdict records from",
    )
    report_parser.add_argument(
        "--explorations-dir",
        type=Path,
        default=DEFAULT_EXPLORATIONS_DIR,
        help="where `report explore` reads exploration artefacts from",
    )
    report_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output path (default: _baseltest/reports/<kind-specific name>)",
    )
    arguments = parser.parse_args(argv)

    if arguments.command == "report":
        try:
            written = report(
                arguments.kind,
                verdict_dir=arguments.verdict_dir,
                explorations_dir=arguments.explorations_dir,
                out=arguments.out,
            )
        except ContractConfigurationError as refusal:
            print("report: nothing to render", file=sys.stderr)
            print(f"  {refusal}", file=sys.stderr)
            return 2
        print(f"report written: {written.as_posix()}")
        return 0

    try:
        if arguments.command == "explore":
            explore(
                arguments.contract_file,
                samples_per_config=arguments.samples_per_config,
                explorations_dir=arguments.explorations_dir,
                html_report=arguments.html_report,
            )
            return 0
        verdict_dir = None
        emit = True
        sizing = ResolvedSizing(samples=arguments.samples)
        if arguments.command == "test":
            if not arguments.no_verdict_xml:
                verdict_dir = arguments.verdict_dir
            emit = not arguments.emit_json
            sizing = _resolve_sizing(arguments)
        result = run(
            arguments.contract_file,
            mode=arguments.command,
            sizing_resolution=sizing,
            baseline_dir=arguments.baseline_dir,
            html_report=arguments.html_report,
            verdict_dir=verdict_dir,
            emit=emit,
        )
    except SizingRefusalError as refusal:
        print(f"{refusal}", file=sys.stderr)
        return 2
    except ContractConfigurationError as refusal:
        print(f"contract {arguments.contract_file}: cannot run as declared", file=sys.stderr)
        print(f"  {refusal}", file=sys.stderr)
        return 2
    except ProviderResponseError as rejection:
        # The provider rejected the request: a configuration problem the
        # message names (schema, model id, credential) — investigable,
        # never a stack trace, never counted as samples.
        print(
            f"contract {arguments.contract_file}: the provider rejected the request",
            file=sys.stderr,
        )
        print(f"  {rejection}", file=sys.stderr)
        return 2
    except InfeasibleRunError as infeasible:
        print(render_infeasible(arguments.contract_file.stem, infeasible), file=sys.stderr)
        return 2
    if arguments.command == "test":
        if result.composite is Verdict.FAIL:
            return 1
        if result.composite is Verdict.INCONCLUSIVE:
            # A latency bound the run's passing samples could not estimate:
            # no judgement was possible, so no assertion can rest on it.
            return 3
        return 0
    if getattr(arguments, "assert_bars", False):
        return _assert_recorded_bars(result)
    return 0  # a plain measure run records; recording cannot fail


def _resolve_sizing(arguments: "argparse.Namespace") -> ResolvedSizing:
    """The ``test`` verb's sizing conversation, before any invocation."""
    declaration = load_contract(arguments.contract_file)
    discover_registrations(arguments.contract_file)
    services = discover_services(arguments.contract_file)
    return resolve_test_sizing(
        declaration,
        services,
        baseline_dir=arguments.baseline_dir,
        samples=arguments.samples,
        tolerate=arguments.tolerate,
        confidence=arguments.confidence,
        power=arguments.power,
        assume_yes=arguments.yes,
        emit_json=arguments.emit_json,
        force=arguments.force,
    )


def _assert_recorded_bars(result: RunResult) -> int:
    """The opt-in assertion: fail after recording, unsupportable distinguished."""
    standings = {
        r.name: bar_standing(r)
        for r in result.criterion_results
        if r.criterion.threshold is not None
    }
    unsupportable = [name for name, standing in standings.items() if standing == "unsupportable"]
    unmet = [name for name, standing in standings.items() if standing == "not met"]
    for name in unsupportable:
        print(
            f"assertion: judgement for criterion {name} is unsupportable at this "
            "sample size — recorded, but no assertion can rest on it",
            file=sys.stderr,
        )
    for name in unmet:
        print(
            f"assertion: declared bar for criterion {name} not met — "
            "failing after recording (the baseline is on disk)",
            file=sys.stderr,
        )
    if unsupportable:
        return 3
    return 1 if unmet else 0


if __name__ == "__main__":
    raise SystemExit(main())
