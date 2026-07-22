"""Load a contract's declaration, registrations, and services exactly once.

The ``test`` verb sizes the run before executing it, and both the sizing
pass and the run proper need the same three parsed inputs. Parsing them
once here and threading the resulting :class:`LoadedContract` into both
keeps a ``test`` invocation to a single parse of each file — the run no
longer re-reads what sizing already read.
"""

from dataclasses import dataclass
from pathlib import Path

from .._parser import ContractDeclaration, load_contract
from .._registrations import discover_registrations
from .._registry import Bindings, Registry
from .._services import ServiceDefinition, discover_services


@dataclass(frozen=True, slots=True)
class LoadedContract:
    """A contract's three parsed inputs, read once and shared.

    ``services`` is the plain mapping the instantiation and sizing passes
    already consume; the bundle is a transient result object (like
    :class:`Instantiation`), frozen so its fields cannot be rebound between
    the two consumers.
    """

    declaration: ContractDeclaration
    registry: Registry
    services: dict[str, ServiceDefinition]


def load_for_run(path: Path, bindings: Bindings | None = None) -> LoadedContract:
    """Parse the contract, its registrations, and its services once.

    The registrations come from the caller-held ``bindings`` when an API
    caller supplies one; otherwise they are discovered from the conventional
    ``mavai-bindings.py`` beside the contract file — the same rule ``run``
    applied when it loaded these itself.
    """
    declaration = load_contract(path)
    registry = bindings._registry if bindings is not None else discover_registrations(path)
    services = discover_services(path, registry)
    return LoadedContract(declaration=declaration, registry=registry, services=services)
