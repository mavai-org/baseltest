"""Registration discovery: the ``mavai-bindings.py`` convention.

Code registrations (``@registry.binding``, ``@registry.check``,
``@registry.transform``) live in the developer's own Python, onto a
:class:`Registry` the module creates. When the runner is driven from the
command line, nothing would import that code — so, mirroring the
services-file convention, a ``mavai-bindings.py`` found beside the contract
file (then in the working directory) is imported before the contract is
instantiated, and the ``registry`` it defines is threaded through the run.
The same trust model as pytest's ``conftest.py`` applies: it is the user's
own project file, executed because they placed it there.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from ._errors import ContractConfigurationError
from ._registry import Registry

REGISTRATIONS_FILENAME = "mavai-bindings.py"
_MODULE_NAME = "mavai_bindings"


def discover_registrations(contract_path: Path) -> Registry:
    """Import the conventional registrations module and yield its registry.

    A ``mavai-bindings.py`` beside the contract file (then in the working
    directory) is imported, and the :class:`Registry` it binds as
    ``registry`` is returned. When the module defines no such registry — or
    no conventions file exists — a fresh empty :class:`Registry` is
    returned (an API caller holds and passes its own instead).
    """
    for directory in (contract_path.parent, Path.cwd()):
        candidate = directory / REGISTRATIONS_FILENAME
        if candidate.is_file():
            module = _import(candidate.resolve())
            registry = getattr(module, "registry", None)
            return registry if isinstance(registry, Registry) else Registry()
    return Registry()


def _import(path: Path) -> ModuleType:
    module_key = f"{_MODULE_NAME}:{path}"
    cached = sys.modules.get(module_key)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ContractConfigurationError(f"cannot import registrations file {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ContractConfigurationError:
        raise
    except Exception as error:
        raise ContractConfigurationError(
            f"the registrations file {path.name} failed to import: {error}"
        ) from error
    sys.modules[module_key] = module
    return module
