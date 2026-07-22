"""Shared runner scaffolding: the artefact-directory layout and progress line.

Every baseltest-generated artefact lives under one visible parent; the
per-verb default directories hang off it. ``_tty_progress`` is the stderr
sampling line the verbs pass to the engine.
"""

import sys
from collections.abc import Callable
from pathlib import Path

# Every baseltest-generated artefact lives under one visible parent in the
# working directory: one root entry, one .gitignore line, one `rm -rf` for a
# clean slate. The leading underscore keeps the directory from shadowing the
# installed package and carries the ecosystem's generated-output signal.
ARTEFACT_ROOT = Path("_baseltest")
DEFAULT_BASELINE_DIR = ARTEFACT_ROOT / "baselines"
DEFAULT_VERDICT_DIR = ARTEFACT_ROOT / "verdicts"
DEFAULT_EXPLORATIONS_DIR = ARTEFACT_ROOT / "explorations"
DEFAULT_OPTIMIZATIONS_DIR = ARTEFACT_ROOT / "optimizations"
DEFAULT_REPORTS_DIR = ARTEFACT_ROOT / "reports"

# Rendering exploration comparisons is the shared family tool's job; this
# framework's half of that split is emitting the canonical artefacts. The
# pointer below is what any request for the old built-in renderer gets.
MAVAI_EXPLORE_POINTER = (
    "exploration comparison reports are rendered by the family's mavai tool: "
    "mavai explore <dir> [-o report.html] — public binaries: "
    "https://github.com/mavai-org/mavai/releases"
)


def _tty_progress(label: str) -> "Callable[[int, int], None] | None":
    """A stderr progress line — only when stderr is a terminal.

    The line overwrites itself while its run is sampling, then persists on
    completion: in a multi-configuration exploration each finished
    configuration leaves its line behind as a progress record instead of
    being erased by the next one. stdout stays clean for the run's actual
    output; non-interactive runs (pipes, CI) see nothing.
    """
    if not sys.stderr.isatty():
        return None

    def on_sample(completed: int, total: int) -> None:
        if completed < total:
            print(
                f"sampling {label}: {completed}/{total}",
                end="\r",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"\r\033[Ksampled {label}: {total}/{total}", file=sys.stderr)

    return on_sample
