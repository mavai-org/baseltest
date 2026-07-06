"""Registration discovery: the ``mavai-bindings.py`` convention.

Code registrations (``@binding``, ``@check``, ``@transform``) live in the
developer's own Python. When the runner is driven from the command line,
nothing would import that code — so, mirroring the services-file
convention, a ``mavai-bindings.py`` found beside the task file (then in
the working directory) is imported before the task is instantiated. The
same trust model as pytest's ``conftest.py`` applies: it is the user's own
project file, executed because they placed it there.
"""

import importlib.util
import sys
from pathlib import Path

from ._errors import TaskConfigurationError

REGISTRATIONS_FILENAME = "mavai-bindings.py"
_MODULE_NAME = "mavai_bindings"


def discover_registrations(task_path: Path) -> Path | None:
    """Import the conventional registrations module, if present.

    Returns the imported file's path, or ``None`` when no conventions file
    exists (an API caller may have registered in-process instead — that
    remains fully supported).
    """
    for directory in (task_path.parent, Path.cwd()):
        candidate = directory / REGISTRATIONS_FILENAME
        if candidate.is_file():
            _import(candidate.resolve())
            return candidate
    return None


def _import(path: Path) -> None:
    module_key = f"{_MODULE_NAME}:{path}"
    if module_key in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise TaskConfigurationError(f"cannot import registrations file {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except TaskConfigurationError:
        raise
    except Exception as error:
        raise TaskConfigurationError(
            f"the registrations file {path.name} failed to import: {error}"
        ) from error
    sys.modules[module_key] = module
