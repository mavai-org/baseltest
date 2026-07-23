"""Service resolution and the inputs ↔ binding join.

Resolving a service reference to the per-sample callable, splatting a
tuple-valued input across positional parameters, and checking the
inputs against the binding's signature before any sample runs.
"""

import inspect
from collections.abc import Callable, Sequence
from typing import Any

from baseltest.contract import FileInput

from .._errors import ContractConfigurationError
from .._registry import Registry
from .._services import ServiceDefinition
from .._signatures import value_fits as _value_fits


def _splat_tuple_invoke(invoke: Callable[..., str]) -> Callable[[Any], str]:
    """Splat a tuple-valued input across the service's positional parameters;
    a scalar input passes straight through."""

    def wrapped(value: Any) -> str:
        return invoke(*value) if isinstance(value, tuple) else invoke(value)

    return wrapped


def _validate_inputs(service: str, fn: Callable[..., str], inputs: Sequence[Any]) -> None:
    """The inputs ↔ per-sample-callable join, checked before any sample runs.

    Arity is always checked; scalar-annotated parameters are checked where
    the signature declares them; unannotated parameters pass through
    untyped. The message carries the introspected signature — the binding's
    signature is the contract, and the reader should never have to go and
    find it.
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):  # no introspectable signature to join against
        return
    rendered = f"{service}{signature}"
    for index, value in enumerate(inputs, start=1):
        arguments = value if isinstance(value, tuple) else (value,)
        try:
            bound = signature.bind(*arguments)
        except TypeError:
            count = f"{len(arguments)} value{'s' if len(arguments) != 1 else ''}"
            raise ContractConfigurationError(
                f"service {service!r}: input {index} ({value!r}) supplies {count} for "
                f"the binding's signature {rendered} — each input must match the "
                "binding's parameters (a list-valued input is splatted positionally)"
            ) from None
        for name, argument in bound.arguments.items():
            parameter = signature.parameters[name]
            if parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
                continue
            annotation = parameter.annotation
            if annotation is str and isinstance(argument, FileInput):
                raise ContractConfigurationError(
                    f"service {service!r}: input {index} supplies file content "
                    f"({argument.kind}: {argument.path.name}) to parameter {name!r}, "
                    "which is typed `str`. A text parameter cannot receive a "
                    "file-sourced part. If this is a language model, sending media to "
                    "the model is not supported in this phase (it arrives with the "
                    "multimodal gateway); if it is your own binding, annotate "
                    f"{name!r} to receive the file (`baseltest.FileInput`) or use a "
                    f"text input. The binding's signature is {rendered}"
                )
            if annotation in (str, int, float, bool) and not _value_fits(argument, annotation):
                raise ContractConfigurationError(
                    f"service {service!r}: input {index}: parameter {name!r} expects "
                    f"{annotation.__name__}, got {type(argument).__name__} "
                    f"({argument!r}) — the binding's signature is {rendered}"
                )


def _resolve_service(
    reference: str, services: dict[str, ServiceDefinition], registry: Registry
) -> tuple[Callable[..., str], dict[str, str]]:
    """Resolve a service reference: definitions first, then the type registry.

    Service names (services-file keys) and type names (the registry) are
    separate namespaces. A definition is a configured instance of a type;
    an *addressable* type — a bare ``@binding`` — is directly usable as a
    service of the same name, the degenerate zero-configuration instance.
    """
    definition = services.get(reference)
    if definition is not None:
        return (
            definition.type.invoker(definition.configuration),
            definition.type.provenance(definition.configuration),
        )
    type_contract = registry.find_type(reference)
    if type_contract is None or type_contract.builtin:
        raise ContractConfigurationError(
            f"service {reference!r} matches no service definition and no registered "
            f"binding. Register the code that invokes your service with "
            f"@bindings.binding({reference!r}) in mavai-bindings.py, or define the service in "
            "mavai-services.yaml, before running the contract."
        )
    if not type_contract.addressable:
        raise ContractConfigurationError(
            f"service {reference!r} names a configurable type directly — a "
            "configurable type is instantiated by a services-file entry; declare a "
            f"service with `type: {reference}` (and its `configuration:`) in "
            "mavai-services.yaml"
        )
    return type_contract.invoker(None), dict(type_contract.covariates)
