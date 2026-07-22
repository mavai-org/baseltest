"""Registration guards: the refusals a registration must pass.

Name non-emptiness, reservedness, and uniqueness for checks and transforms
(`_register`), and covariate well-formedness plus the framework-reserved
provenance keys (`_validated_covariates`, `RESERVED_COVARIATE_KEYS`).
"""

from typing import Any

from .._errors import ContractConfigurationError

# Provenance keys the framework itself writes into every baseline artefact:
# the binding name, the run-identity keys, and the service-type marker. A
# covariate or configuration key under one of these names would collide
# with the framework's own entry, so registration and parsing refuse it.
RESERVED_COVARIATE_KEYS = frozenset({"binding", "runMode", "serviceType", "taskFile", "taskFormat"})


def _register(
    registry: dict[str, Any], kind: str, name: str, fn: Any, reserved: tuple[str, ...] = ()
) -> None:
    if not name:
        raise ContractConfigurationError(f"a {kind} name must be non-empty")
    if name in reserved:
        raise ContractConfigurationError(
            f"{kind} name {name!r} is reserved for the format's stock {kind}s"
        )
    if name in registry:
        raise ContractConfigurationError(
            f"a {kind} named {name!r} is already registered; names must be unique"
        )
    registry[name] = fn


def _validated_covariates(name: str, covariates: dict[str, str] | None) -> dict[str, str]:
    """Refuse malformed or framework-colliding covariates at registration time."""
    if covariates is None:
        return {}
    for key, value in covariates.items():
        if not isinstance(key, str) or not key:
            raise ContractConfigurationError(
                f"binding {name!r}: covariate keys must be non-empty strings, got {key!r}"
            )
        if key in RESERVED_COVARIATE_KEYS:
            reserved = ", ".join(sorted(RESERVED_COVARIATE_KEYS))
            raise ContractConfigurationError(
                f"binding {name!r}: covariate key {key!r} is reserved for the framework's "
                f"own provenance entries ({reserved}) — choose another name"
            )
        if not isinstance(value, str):
            raise ContractConfigurationError(
                f"binding {name!r}: covariate {key!r} must be a string, got "
                f"{type(value).__name__} — format the value explicitly; identity is "
                "compared verbatim"
            )
    return dict(covariates)
