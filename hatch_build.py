"""Build hook: carry the report renderer in the wheel that has one.

baseltest delegates every HTML report to ``mavai``, the family's renderer.
Delegating to a tool the reader has to find and install themselves makes
two installations out of one, for a binary whose only purpose is to draw
what baseltest just wrote. So a platform wheel carries it.

The renderer is a compiled executable for one platform, which is what makes
this a build-time question rather than a dependency: the same source builds
five different wheels, and one more that carries nothing.

- With ``MAVAI_BINARY`` naming an executable, the wheel installs it into the
  environment's scripts directory under the name that platform gives an
  executable, and is tagged for the platform named by
  ``MAVAI_WHEEL_PLATFORM``. The reader gets ``mavai`` on their PATH, and
  ``basel --html-report`` finds it without one.
- With neither set, the build is the ordinary pure-Python wheel: a complete
  framework that runs experiments and writes artefacts, and says plainly
  what it cannot do when a report is asked of it. This is what an
  unsupported platform installs, and what an sdist builds — a source
  distribution must never carry a binary for a platform it cannot name.

Both variables are required together. Setting one alone is a mistake in the
release workflow rather than a build to guess at, so it is refused.
"""

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BINARY = "MAVAI_BINARY"
PLATFORM = "MAVAI_WHEEL_PLATFORM"

#: The renderer's command name, as the family publishes it. The same name
#: the framework's renderer lookup asks the scripts directory for.
RENDERER = "mavai"


def script_name(platform: str) -> str:
    """What ``platform`` calls the renderer once it is installed.

    The name is not free: ``baseltest.declarative._report.bundled_renderer``
    reads this exact filename out of the environment's scripts directory, and
    it asks for the name the platform uses — ``mavai.exe`` on Windows, where
    an extensionless file is not a command at all. This hook is the half of
    that one decision which knows the platform, so the name is derived from
    the wheel's tag rather than written as a literal on both sides.
    """
    return f"{RENDERER}.exe" if platform.startswith("win") else RENDERER


class RendererBundleHook(BuildHookInterface):
    """Puts the renderer in the wheel, and tags the wheel for its platform."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        binary = os.environ.get(BINARY)
        platform = os.environ.get(PLATFORM)

        if not binary and not platform:
            return

        if not binary or not platform:
            message = (
                f"{BINARY} and {PLATFORM} are set together or not at all: "
                f"a wheel carrying a renderer must be tagged for the platform "
                f"it was built for, and a wheel tagged for a platform must "
                f"carry the renderer that made it one"
            )
            raise ValueError(message)

        executable = Path(binary)
        if not executable.is_file():
            message = f"{BINARY} names {binary}, which is not a file"
            raise ValueError(message)

        # The renderer on the reader's PATH, and the one file the framework's
        # own renderer lookup resolves — it reads the scripts directory
        # directly rather than trusting PATH, so a single copy serves both.
        build_data["shared_scripts"] = {str(executable): script_name(platform)}
        # Not pure Python any more: the wheel carries an executable for one
        # platform, and its tag has to say so or pip will offer it to every
        # platform.
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{platform}"
