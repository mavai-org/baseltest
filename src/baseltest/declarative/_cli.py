"""The ``basel`` console script — the `baseltest` package's command."""

import argparse
import sys
from pathlib import Path

from baseltest._version import __version__
from baseltest.engine import (
    DefectDiagnosisError,
    InfeasibleRunError,
    RunResult,
    Verdict,
    bar_attainment,
)
from baseltest.reporting import render_infeasible

from . import _report
from ._errors import ContractConfigurationError
from ._parser import load_contract
from ._providers import ProviderResponseError
from ._runner import (
    DEFAULT_BASELINE_DIR,
    DEFAULT_EXPLORATIONS_DIR,
    DEFAULT_OPTIMIZATIONS_DIR,
    DEFAULT_VERDICT_DIR,
    LoadedContract,
    check,
    explore,
    load_for_run,
    optimize,
    run,
)
from ._sizing import ResolvedSizing, SizingRefusalError, resolve_test_sizing


class _StateVersions(argparse.Action):
    """``--version``: this build on stdout, the renderer it carries on stderr.

    Two installations answer a report request differently — one carrying a
    bundled renderer, one finding the family's on PATH, one carrying none —
    and the difference is otherwise invisible until a report is asked for.

    Which stream each goes to is not cosmetic. The version string on stdout
    is byte-identical to the verdict record's ``generator`` attribute, so a
    reader holding an artefact can compare the two directly; a second line
    there would break that comparison for every existing caller. The
    renderer line is a diagnostic about this environment, so it goes where
    the family puts diagnostics.

    The renderer is named here rather than at parser construction because
    naming it costs a subprocess, which every invocation of every other verb
    would otherwise pay.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        print(f"baseltest {__version__}")
        print(f"report renderer: {_report.renderer_disclosure()}", file=sys.stderr)
        parser.exit()


def _add_verb(
    subparsers: argparse._SubParsersAction,  # noqa: SLF001
    verb: str,
    description: str,
) -> argparse.ArgumentParser:
    """Register a verb, stating what it does on both screens it appears on.

    The one sentence is the verb's entry in ``basel --help`` and the opening
    line of ``basel <verb> --help``. Passing it once is what keeps the two
    from drifting apart, which is how the second came to state nothing at
    all.
    """
    return subparsers.add_parser(verb, help=description, description=description)


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``basel`` argument parser: the verbs and their flags."""
    parser = argparse.ArgumentParser(
        prog="basel",
        description="Statistically honest testing for stochastic services.",
        # Each verb carries its own flags, and this screen lists none of them:
        # a reader looking here for --html-report concludes it does not exist.
        epilog="Each verb takes its own options: basel <verb> --help.",
    )
    # Naming the distribution rather than the command, so this string and the
    # one the verdict record's generator attribute carries are the same string:
    # a reader holding an artefact can ask the tool whether it wrote it.
    parser.add_argument(
        "--version",
        action=_StateVersions,
        nargs=0,
        help="print the version and the report renderer, and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for verb, description in (
        ("test", "judge the contract's thresholded criteria: a probabilistic test"),
        ("measure", "record every criterion and persist the baseline artefact"),
    ):
        verb_parser = _add_verb(subparsers, verb, description)
        verb_parser.add_argument("contract_file", type=Path, help="path to the contract file")
        # The same directory, read by one verb and written by the other: a
        # measure run persists the baseline a later test sizes itself against.
        # Stating only the writing direction left the flag looking irrelevant
        # on the verb that reads it.
        verb_parser.add_argument(
            "--baseline-dir",
            type=Path,
            default=DEFAULT_BASELINE_DIR,
            help=(
                "directory the baseline artefact is persisted into"
                if verb == "measure"
                else "directory the proven baseline is read from"
            ),
        )
        verb_parser.add_argument(
            "--html-report",
            type=Path,
            default=None,
            help=(
                "render the run's artefacts to this path as a self-contained HTML "
                "report, by handing them to mavai — the family's report renderer, "
                "which must be on PATH. Never changes the verb's exit code."
            ),
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
                "--accept-weak-design",
                action="store_true",
                help="accept a weak design without the confirmation prompt (for automation)",
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
    explore_parser = _add_verb(
        subparsers,
        "explore",
        (
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
        help=(
            "render the run's artefacts to this path as a self-contained HTML "
            "report, by handing them to mavai — the family's report renderer, "
            "which must be on PATH. Never changes the verb's exit code."
        ),
    )
    optimize_parser = _add_verb(
        subparsers,
        "optimize",
        (
            "run one declared optimization: iterative configuration search, "
            "scored per iteration, full history persisted — descriptive, "
            "never a verdict"
        ),
    )
    optimize_parser.add_argument("contract_file", type=Path, help="path to the contract file")
    optimize_parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        metavar="id",
        help=(
            "the optimization entry to run; required when the service declares "
            "several (a lone entry runs without it)"
        ),
    )
    optimize_parser.add_argument(
        "--all",
        dest="all_entries",
        action="store_true",
        help="run every declared optimization entry — each is an independent experiment",
    )
    optimize_parser.add_argument(
        "--samples-per-iteration",
        type=int,
        default=None,
        help="samples per iteration (default: 20)",
    )
    optimize_parser.add_argument(
        "--optimizations-dir",
        type=Path,
        default=DEFAULT_OPTIMIZATIONS_DIR,
        help="directory optimization artefacts are written into (one file per run id)",
    )
    optimize_parser.add_argument(
        "--html-report",
        type=Path,
        default=None,
        help=(
            "render the run's artefacts to this path as a self-contained HTML "
            "report, by handing them to mavai — the family's report renderer, "
            "which must be on PATH. Never changes the verb's exit code."
        ),
    )
    # Rendering is the second stage of every verb that writes artefacts, and
    # a reader does not always want it at the moment the samples are drawn.
    # The verb names the stage; its first argument names the kind, so the
    # four the framework runs stay the four it reports on.
    report_parser = _add_verb(
        subparsers,
        "report",
        (
            "render artefacts a previous run wrote — the same report "
            "--html-report draws, without paying for the run again"
        ),
    )
    report_parser.add_argument(
        "kind",
        choices=sorted(_report.REPORT_OF),
        help="which run's artefacts to report on",
    )
    report_parser.add_argument(
        "contract_file",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "narrow the report to one contract's artefacts (explore and "
            "optimize only — verdicts and baselines are not written per "
            "contract); omitted, every contract in the directory is reported"
        ),
    )
    report_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="write the report here; omitted, it goes to stdout",
    )
    # Every directory flag, because the kind is an argument rather than four
    # verbs: whichever kind is named reads the one that holds its artefacts,
    # spelled exactly as the run that wrote them spelled it. Each is named in
    # the help beside the kind it serves — a run that wrote somewhere other
    # than the default is exactly the run whose reader needs to say so here,
    # and a flag absent from the help cannot be reached by anyone who did not
    # already know it existed.
    for flag, default, kind in (
        ("--baseline-dir", DEFAULT_BASELINE_DIR, "measure"),
        ("--verdict-dir", DEFAULT_VERDICT_DIR, "test"),
        ("--explorations-dir", DEFAULT_EXPLORATIONS_DIR, "explore"),
        ("--optimizations-dir", DEFAULT_OPTIMIZATIONS_DIR, "optimize"),
    ):
        report_parser.add_argument(
            flag,
            type=Path,
            default=default,
            help=f"where the {kind} artefacts are, when the run did not write them to the default",
        )
    check_parser = _add_verb(
        subparsers,
        "check",
        (
            "validate the contract against its services file and bindings — every "
            "load-time join, zero samples; the authoring loop's compile step"
        ),
    )
    check_parser.add_argument("contract_file", type=Path, help="path to the contract file")
    check_parser.add_argument(
        "--explorations-dir",
        type=Path,
        default=DEFAULT_EXPLORATIONS_DIR,
        help=(
            "where the stale-artefact advisory looks for the active experiment's "
            "exploration artefacts (advisory only — nothing is deleted)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: the ``test`` / ``measure`` / ``explore`` verbs over a contract file."""
    arguments = _build_parser().parse_args(argv)

    refusal = _refuse_unrenderable_report(arguments)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2

    if arguments.command == "report":
        return _render_written_artefacts(arguments)

    if arguments.command == "check":
        try:
            facts = check(arguments.contract_file, explorations_dir=arguments.explorations_dir)
        except ContractConfigurationError as refusal:
            print(f"contract {arguments.contract_file}: cannot run as declared", file=sys.stderr)
            print(f"  {refusal}", file=sys.stderr)
            return 2
        for fact in facts:
            if fact.startswith("(unverified) "):
                print(f"ok (unverified): {fact[len('(unverified) ') :]}")
            elif fact.startswith(("stale: ", "note: ")):
                # The pre-flight advisory: named, never judged — the
                # operator deletes; the tool only says what it sees.
                print(fact)
            else:
                print(f"ok: {fact}")
        return 0

    try:
        if arguments.command == "optimize":
            if arguments.run_id is not None and arguments.all_entries:
                print(
                    "optimize: name one entry or pass --all, not both",
                    file=sys.stderr,
                )
                return 2
            optimize_outcomes = optimize(
                arguments.contract_file,
                run_id=arguments.run_id,
                all_entries=arguments.all_entries,
                samples_per_iteration=arguments.samples_per_iteration,
                optimizations_dir=arguments.optimizations_dir,
            )
            _render_report(arguments, arguments.optimizations_dir)
            # A defect stopped at least one entry's search: a partial run,
            # reported and signalled — not a silent success.
            return 1 if any(o.defect is not None for o in optimize_outcomes) else 0
        if arguments.command == "explore":
            exploration = explore(
                arguments.contract_file,
                samples_per_config=arguments.samples_per_config,
                explorations_dir=arguments.explorations_dir,
            )
            # This run's own contract directory, not the explorations root:
            # an exploration groups its artefacts by the keys it sweeps, so
            # its documents sit one level deeper than every other kind's and
            # the root has nothing directly beneath it to render.
            _render_report(
                arguments,
                _explored_contract_directory(
                    Path(arguments.explorations_dir),
                    load_contract(arguments.contract_file).contract,
                ),
            )
            # A defect contained to a configuration leaves the others' artefacts
            # written; the partial run is signalled by a non-zero exit.
            return 1 if exploration.aborted else 0
        verdict_dir = None
        emit = True
        # Parse the contract, its registrations, and its services once; the
        # test verb's sizing pass and the run proper both read the same bundle.
        loaded = load_for_run(arguments.contract_file)
        sizing = ResolvedSizing(samples=arguments.samples)
        if arguments.command == "test":
            if not arguments.no_verdict_xml:
                verdict_dir = arguments.verdict_dir
            emit = not arguments.emit_json
            sizing = _resolve_sizing(arguments, loaded)
        result = run(
            arguments.contract_file,
            mode=arguments.command,
            sizing_resolution=sizing,
            baseline_dir=arguments.baseline_dir,
            verdict_dir=verdict_dir,
            emit=emit,
            loaded=loaded,
        )
        # mavai groups documents by the directory beneath the one it is
        # given. Explorations and optimizations are already written under a
        # per-service directory; verdicts and baselines are written flat, so
        # the renderer is handed their parent and the directory itself
        # becomes the grouping.
        flat = verdict_dir if arguments.command == "test" else arguments.baseline_dir
        _render_report(arguments, Path(flat).parent if flat is not None else None)
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
    except DefectDiagnosisError as defect:
        # A defect escaped a transform in a single-configuration run (test or
        # measure): stop with the diagnosis, not a stack trace. Multi-config
        # explore/optimize contain defects per configuration and never reach
        # here.
        print(f"contract {arguments.contract_file}: a defect stopped the run", file=sys.stderr)
        print(f"  {defect}", file=sys.stderr)
        return 1
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


def _explored_contract_directory(explorations_dir: Path, contract_id: str) -> Path:
    """The directory an exploration of ``contract_id`` wrote its grid into.

    One level below the explorations directory, because an exploration
    groups its artefacts by the keys it sweeps — so the directory mavai is
    given is the contract's, and the swept-key directories beneath it are
    what it groups.
    """
    return explorations_dir / contract_id


def _sole_explored_contract(explorations_dir: Path) -> Path | str:
    """The one contract explored here, or why that question has no answer.

    Naming the contract is how an explore report finds its directory. Where
    exactly one has been explored the answer is not in doubt, and asking for
    it would be ceremony; where several have, guessing would draw a report
    about a contract the reader did not ask for.
    """
    explored = sorted(p for p in explorations_dir.iterdir() if p.is_dir())
    if len(explored) == 1:
        return explored[0]
    if not explored:
        return (
            f"no explore artefacts under {explorations_dir.as_posix()}\n"
            f"  run: basel explore <contract>"
        )
    names = "\n".join(f"    {p.name}" for p in explored)
    return (
        f"{len(explored)} contracts have been explored under "
        f"{explorations_dir.as_posix()}, and a report is drawn over one:\n"
        f"{names}\n"
        f"  name the contract file whose report you want"
    )


def _artefact_directory(arguments: argparse.Namespace) -> Path:
    """Where a non-explore kind's artefacts were written.

    The same directories the run verbs hand the renderer, and for the same
    reason where a parent is handed instead: mavai groups documents by the
    directory beneath the one it is given, and verdicts and baselines are
    written flat, so the directory holding them is itself the grouping.
    """
    if arguments.kind == "optimize":
        return Path(arguments.optimizations_dir)
    flat = arguments.verdict_dir if arguments.kind == "test" else arguments.baseline_dir
    return Path(flat).parent


def _render_written_artefacts(arguments: argparse.Namespace) -> int:
    """``basel report <kind> [contract]``: draw what a previous run wrote.

    No service is invoked and no sample is drawn. This is the second stage
    of a run, on its own — and asking for it later must produce exactly what
    asking for it during the run would have.
    """
    renderer = _report.locate_renderer()
    if renderer is None:
        print(_report.RENDERER_MISSING, file=sys.stderr)
        return 2

    if arguments.kind == _report.CONTRACT_SCOPED:
        explorations = Path(arguments.explorations_dir)
        if arguments.contract_file is not None:
            try:
                declared = load_contract(arguments.contract_file)
            except ContractConfigurationError as refusal:
                print(f"contract {arguments.contract_file}: cannot be read", file=sys.stderr)
                print(f"  {refusal}", file=sys.stderr)
                return 2
            artefacts = _explored_contract_directory(explorations, declared.contract)
        elif not explorations.is_dir():
            print(
                f"no explore artefacts under {explorations.as_posix()}\n"
                f"  run: basel explore <contract>",
                file=sys.stderr,
            )
            return 2
        else:
            inferred = _sole_explored_contract(explorations)
            if isinstance(inferred, str):
                print(inferred, file=sys.stderr)
                return 2
            artefacts = inferred
    else:
        if arguments.contract_file is not None:
            # Refused rather than ignored: a reader who named a contract and
            # silently got every contract would believe a report that is not
            # about what they asked for.
            print(
                f"report {arguments.kind}: a contract cannot narrow this report — "
                f"every {arguments.kind} run written so far is drawn together\n"
                f"  drop the contract",
                file=sys.stderr,
            )
            return 2
        artefacts = _artefact_directory(arguments)

    if not artefacts.is_dir():
        # Naming the run that would fill it: the reader asked for a report of
        # something that was never written, which is a different thing from a
        # report that failed to draw.
        print(
            f"no {arguments.kind} artefacts under {artefacts.as_posix()}\n"
            f"  run: basel {arguments.kind} <contract>",
            file=sys.stderr,
        )
        return 2

    failure = _report.render(
        renderer, _report.REPORT_OF[arguments.kind], artefacts, arguments.output
    )
    if failure is not None:
        print(failure, file=sys.stderr)
        return 1
    return 0


def _refuse_unrenderable_report(arguments: argparse.Namespace) -> str | None:
    """Why this invocation could not produce the report it was asked for.

    Checked before the run, not after: samples cost money and time, and a
    reader who asked for a report should not pay for one only to be told at
    the end that nothing could render it.
    """
    if getattr(arguments, "html_report", None) is None:
        return None
    if arguments.command == "test" and arguments.no_verdict_xml:
        return (
            "--html-report renders the verdict record, which --no-verdict-xml "
            "suppresses: ask for one or the other"
        )
    if _report.locate_renderer() is None:
        return _report.RENDERER_MISSING
    return None


def _render_report(arguments: argparse.Namespace, artefacts: str | Path | None) -> None:
    """Hand the artefacts just written to the renderer.

    Never changes the verb's exit code. The run's verdict is what the caller
    asked about; a report that could not be drawn is loud on stderr but does
    not restate the verdict, and a passing run that failed to render is still
    a passing run.
    """
    if getattr(arguments, "html_report", None) is None:
        return
    renderer = _report.locate_renderer()
    if renderer is None or artefacts is None:
        # Preflight refused both of these before any sample was drawn;
        # reaching here means PATH changed under a running experiment.
        print(_report.RENDERER_MISSING, file=sys.stderr)
        return
    failure = _report.render(
        renderer, _report.REPORT_OF[arguments.command], Path(artefacts), arguments.html_report
    )
    if failure is not None:
        # The run's own outcome is stated separately and stands: this is the
        # report failing, not the experiment.
        print(f"{failure} (the run itself is unaffected)", file=sys.stderr)


def _resolve_sizing(arguments: "argparse.Namespace", loaded: LoadedContract) -> ResolvedSizing:
    """The ``test`` verb's sizing conversation, before any invocation.

    Works from the already-parsed ``loaded`` bundle — the run that follows
    reuses the same declaration, registry, and services, so the contract is
    read once per invocation.
    """
    return resolve_test_sizing(
        loaded.declaration,
        loaded.services,
        baseline_dir=arguments.baseline_dir,
        samples=arguments.samples,
        tolerate=arguments.tolerate,
        confidence=arguments.confidence,
        power=arguments.power,
        accept_weak_design=arguments.accept_weak_design,
        emit_json=arguments.emit_json,
        force=arguments.force,
        registry=loaded.registry,
    )


def _assert_recorded_bars(result: RunResult) -> int:
    """The opt-in assertion: fail after recording, unsupportable distinguished."""
    standings = {
        r.name: bar_attainment(r)
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
