"""Handing a run's artefacts to mavai, the family's report renderer.

baseltest renders no HTML. A run's product is its artefacts; turning those
into a page is one job, done once, for the whole family — so punit, feotest
and baseltest all show a reader the same report of the same run rather than
three renderings that drift apart. This module is the seam: it finds the
renderer and gives it the directory the run just wrote.

The seam is deliberately thin. baseltest states the report type, the
directory and the destination, and nothing else — mavai's own options stay
mavai's, reachable by running it directly. Restating them here would grow a
second copy of an interface that already exists, and the two copies would
drift the moment either tool moved.
"""

import shutil
import subprocess
from pathlib import Path

#: The renderer's command name, as the family publishes it.
RENDERER = "mavai"

#: Which report each verb's artefacts make. A verb writes one kind of
#: artefact and mavai reads one kind per report, so the mapping is total.
REPORT_OF = {
    "test": "verdict",
    "measure": "measure",
    "explore": "explore",
    "optimize": "optimize",
}

RENDERER_MISSING = (
    f"the HTML report is rendered by {RENDERER}, the mavai family's report "
    f"renderer, which is not on PATH\n"
    f"  install it from https://github.com/mavai-org/mavai/releases\n"
    f"  or omit --html-report and render the artefacts later"
)


def locate_renderer() -> str | None:
    """The renderer's path, or ``None`` where it is not installed."""
    return shutil.which(RENDERER)


def render(renderer: str, report: str, artefacts: Path, output: Path) -> str | None:
    """Render ``artefacts`` to ``output``, returning a diagnostic on failure.

    The renderer's own stdout and stderr are inherited, so its diagnostics
    reach the reader as it wrote them rather than paraphrased here.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(  # noqa: S603 - a fixed argument vector, never a shell
        [renderer, report, str(artefacts), "-o", str(output)],
        check=False,
    )
    if completed.returncode != 0:
        return (
            f"{RENDERER} {report} exited {completed.returncode}: no report was written to "
            f"{output.as_posix()} (the run itself is unaffected)"
        )
    return None
