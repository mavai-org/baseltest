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

import os
import shutil
import subprocess
import sysconfig
from pathlib import Path

#: The renderer's command name, as the family publishes it.
RENDERER = "mavai"

#: Names an executable to use instead of any other. The escape hatch for a
#: local build of the renderer, and the only way to override what the
#: installation carries.
RENDERER_OVERRIDE = "MAVAI_BIN"

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
    f"renderer, and this installation of baseltest does not carry one\n"
    f"  install a platform wheel — pip install baseltest — which bundles it,\n"
    f"  or install {RENDERER} from https://github.com/mavai-org/mavai/releases,\n"
    f"  or omit --html-report and render the artefacts later"
)


def _executable(candidate: Path) -> str | None:
    """``candidate`` as a usable command, or ``None``."""
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def bundled_renderer() -> str | None:
    """The renderer this installation carries, or ``None`` if it carries none.

    A platform wheel installs the executable into the environment's scripts
    directory, so it is on PATH for the reader who wants to run it directly.
    Looking there rather than relying on PATH is deliberate: an interpreter
    invoked by absolute path, or a launcher that does not activate the
    environment, has the renderer installed but not on the search path, and
    the report should not depend on which of those a caller did.
    """
    scripts = sysconfig.get_path("scripts")
    if not scripts:
        return None
    name = f"{RENDERER}.exe" if os.name == "nt" else RENDERER
    return _executable(Path(scripts) / name)


def locate_renderer() -> str | None:
    """The renderer this invocation should use, or ``None`` where there is none.

    First match wins, and the order states the precedence: an explicit
    override answers to nobody, an installation's own renderer is the one it
    was built with, and PATH is the long-standing route for an environment
    that carries no bundled renderer at all.
    """
    override = os.environ.get(RENDERER_OVERRIDE)
    if override:
        # A stated override that does not resolve is a mistake worth
        # surfacing, not something to quietly fall through: the caller asked
        # for a specific renderer and would otherwise get a different one.
        return _executable(Path(override))
    return bundled_renderer() or shutil.which(RENDERER)


def renderer_disclosure() -> str:
    """One line naming the renderer this installation would use."""
    located = locate_renderer()
    if located is None:
        return f"no {RENDERER} report renderer (see --html-report)"
    stated = subprocess.run(  # noqa: S603 - a fixed argument vector, never a shell
        [located, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version = stated.stdout.strip() if stated.returncode == 0 else "version unstated"
    origin = "bundled" if located == bundled_renderer() else located
    return f"{version} ({origin})"


#: Which verbs write their artefacts under a directory per contract, and so
#: can have a report narrowed to one. Verdicts and baselines are written
#: flat, carrying the contract in the filename — and selecting them by that
#: would mean reading a naming convention, which no consumer in this family
#: does.
SCOPED_BY_CONTRACT = frozenset({"explore", "optimize"})


def render(renderer: str, report: str, artefacts: Path, output: Path | None) -> str | None:
    """Render ``artefacts``, returning a diagnostic on failure.

    ``output`` names a file, or is ``None`` for the renderer's own default of
    stdout — so a report can be piped, as everything else in the family can.

    The renderer's own stdout and stderr are inherited, so its diagnostics
    reach the reader as it wrote them rather than paraphrased here.
    """
    destination = []
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        destination = ["-o", str(output)]
    completed = subprocess.run(  # noqa: S603 - a fixed argument vector, never a shell
        [renderer, report, str(artefacts), *destination],
        check=False,
    )
    if completed.returncode != 0:
        wrote = f"no report was written to {output.as_posix()}" if output else "no report was drawn"
        return f"{RENDERER} {report} exited {completed.returncode}: {wrote}"
    return None
