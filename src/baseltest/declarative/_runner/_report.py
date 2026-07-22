"""The ``report`` verb: render an HTML report from persisted artefacts.

Never executes anything. ``test`` sweeps the verdict records; ``explore`` is
the family tool's job (the refusal names it); ``measure`` is reserved.
"""

import sys
from pathlib import Path

from baseltest.reporting import read_verdict_directory, render_test_report

from .._disclosure import sizing_disclosure
from .._errors import ContractConfigurationError
from ._shared import DEFAULT_REPORTS_DIR, DEFAULT_VERDICT_DIR, MAVAI_EXPLORE_POINTER


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
