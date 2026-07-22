"""View construction: a contract's declared transforms as callables.

A view is a named transformation applied to a raw service response before
a postcondition inspects it. A declared output schema on a transform is a
claim, so it is checked always-on: every trial's actual output is
validated, and a violation is a named trial failure.
"""

from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator

from baseltest.contract import TransformError

from .._parser import ContractDeclaration
from .._registry import Registry
from .._structured import STOCK_TRANSFORMS as STOCK_TRANSFORM_FNS


def _build_views(
    declaration: ContractDeclaration, registry: Registry
) -> dict[str, Callable[[str], Any]]:
    views: dict[str, Callable[[str], Any]] = {}
    for view_name, transformation in declaration.transforms.items():
        stock = STOCK_TRANSFORM_FNS.get(transformation)
        if stock is not None:
            views[view_name] = stock
            continue
        registration = registry.transform_registration(transformation)
        fn = registration.fn
        if registration.output_schema is not None:
            # A declared schema is a claim; claims are checked — always-on:
            # every trial's actual output is validated, and a violation is
            # a named trial failure (view-shape drift surfaced honestly,
            # never a silent empty selection).
            fn = _schema_checked_view(view_name, fn, registration.output_schema)
        views[view_name] = fn
    return views


def _schema_checked_view(
    view_name: str, fn: Callable[[str], Any], schema: dict[str, Any]
) -> Callable[[str], Any]:
    validator = Draft202012Validator(schema)

    def compute(raw: str) -> Any:
        value = fn(raw)
        error = next(validator.iter_errors(value), None)
        if error is not None:
            at = f" (at {error.json_path})" if error.json_path != "$" else ""
            raise TransformError(
                f"view {view_name!r} violates its declared output schema: {error.message}{at}"
            )
        return value

    return compute


def descriptive_view_fingerprints(
    declaration: ContractDeclaration, registry: Registry
) -> dict[str, str]:
    """Fingerprints of the contract's declared view output schemas.

    Recorded descriptively in baseline artefacts — visible and diffable,
    never compared: a transformation's output schema executes after the
    response exists and has no influence on the service's behaviour, so
    it is never a covariate and never enters provenance or the drift
    comparison. (The response-schema, by contrast, always influences the
    service and travels in provenance as a covariate.)
    """
    fingerprints: dict[str, str] = {}
    for view_name, transformation in declaration.transforms.items():
        if transformation in STOCK_TRANSFORM_FNS:
            continue
        registration = registry.transform_registration(transformation)
        if registration.fingerprint is not None:
            fingerprints[view_name] = registration.fingerprint
    return fingerprints
