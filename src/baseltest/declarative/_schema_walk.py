"""Static resolution of JSONPath expressions against JSON Schema declarations.

The check verb's path ↔ declared-shape join: when a view's value has a
declared schema (the service's ``response-schema`` for the parsed
response, a transformation's declared output schema for a derived view),
the validity of a contract's ``path:`` expressions against that shape is
decidable at load time for the bread-and-butter subset — member access,
array indices, wildcards, union branches. A mistyped path is refused
before a single sample is paid for, with the failing segment named and
the declared keys beside it; what is not decidable (filters, slices,
recursive descent, ``$ref``) **passes unverified, visibly** — no false
refusals, ever.

The path side of the walk is the compiled ``jsonpath-rfc9535`` query's
own segment/selector AST — the very object the runtime evaluates, so
there is no second parse to drift. The schema side is a plain walk over
the schema mapping. No library exists for this join; it is composed here
from the two halves the reader already holds.
"""

import difflib
from dataclasses import dataclass
from typing import Any

from jsonpath_rfc9535.segments import JSONPathChildSegment
from jsonpath_rfc9535.selectors import (
    IndexSelector,
    NameSelector,
    WildcardSelector,
)

from baseltest.engine.naming import bounded_excerpt

from ._errors import ContractConfigurationError

VERIFIED = "verified"
UNVERIFIED = "unverified"

# Union expansion depth: structured-output schemas are shallow; a bound
# this generous is a cycle guard, not a capability limit.
_MAX_BRANCH_DEPTH = 32


@dataclass(frozen=True, slots=True)
class WalkFailure:
    """Why a path cannot resolve — everything a friendly refusal needs.

    Attributes:
        segment: The failing segment, as the author wrote it (e.g.
            ``statments`` or ``[*]``).
        prefix: The expression resolved so far, including the failing
            segment (e.g. ``$.statments``) — where in the path the walk
            stopped.
        declared: The keys the schema actually declares at that point
            (empty when the failure is a type mismatch, not a name miss).
        nearest: The closest declared key to the failing name, when one
            is plausibly a typo target.
        detail: The one-line explanation of the mismatch.
    """

    segment: str
    prefix: str
    declared: tuple[str, ...]
    nearest: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class WalkOutcome:
    """One expression's static verdict: verified, unverified, or a failure."""

    status: str
    failure: WalkFailure | None = None


def _branches(schema: Any, depth: int = 0) -> tuple[list[dict[str, Any]], bool]:
    """Expand a schema into its union branches.

    Returns the resolvable mapping branches and whether any branch is
    beyond static reach (``$ref``, boolean ``true``, non-mapping, depth) —
    the caller must degrade to unverified rather than refuse when so.
    """
    if depth > _MAX_BRANCH_DEPTH:
        return [], True
    if schema is True:
        return [], True
    if schema is False:
        return [], False
    if not isinstance(schema, dict):
        return [], True
    if "$ref" in schema:
        return [], True
    branches: list[dict[str, Any]] = []
    unreachable = False
    nested = [schema.get(key) for key in ("anyOf", "oneOf", "allOf")]
    if any(isinstance(entry, list) for entry in nested):
        for entry in nested:
            if not isinstance(entry, list):
                continue
            for sub in entry:
                sub_branches, sub_unreachable = _branches(sub, depth + 1)
                branches.extend(sub_branches)
                unreachable = unreachable or sub_unreachable
        # A union wrapper may still carry its own constraints beside the
        # branch list; treating the wrapper as one more branch keeps the
        # no-false-refusals guarantee.
        residue = {k: v for k, v in schema.items() if k not in ("anyOf", "oneOf", "allOf")}
        if residue.get("properties") or residue.get("items"):
            branches.append(residue)
        return branches, unreachable
    return [schema], False


def _admits(branch: dict[str, Any], kind: str) -> bool:
    """Whether the branch's ``type`` admits the JSON kind (absent type admits all)."""
    declared = branch.get("type")
    if declared is None:
        return True
    types = declared if isinstance(declared, list) else [declared]
    return kind in types


def _descend_name(
    schemas: list[Any], name: str
) -> tuple[list[Any], bool, tuple[str, ...], list[str]]:
    """One name segment: (next schemas, unverifiable?, declared keys, dead-end types)."""
    next_schemas: list[Any] = []
    unverifiable = False
    declared: list[str] = []
    dead_types: list[str] = []
    for schema in schemas:
        branches, unreachable = _branches(schema)
        unverifiable = unverifiable or unreachable
        for branch in branches:
            if not _admits(branch, "object"):
                kinds = branch.get("type")
                dead_types.extend(kinds if isinstance(kinds, list) else [str(kinds)])
                continue
            properties = branch.get("properties")
            if isinstance(properties, dict):
                declared.extend(str(key) for key in properties)
                if name in properties:
                    next_schemas.append(properties[name])
                    continue
            if "patternProperties" in branch:
                unverifiable = True
                continue
            additional = branch.get("additionalProperties")
            if additional is False:
                continue  # a definite dead end for this name
            if isinstance(additional, dict):
                next_schemas.append(additional)
            else:
                unverifiable = True  # open object: cannot refute the name
    return next_schemas, unverifiable, tuple(dict.fromkeys(declared)), dead_types


def _descend_items(schemas: list[Any]) -> tuple[list[Any], bool, list[str]]:
    """One index/wildcard segment: (next schemas, unverifiable?, dead-end types)."""
    next_schemas: list[Any] = []
    unverifiable = False
    dead_types: list[str] = []
    for schema in schemas:
        branches, unreachable = _branches(schema)
        unverifiable = unverifiable or unreachable
        for branch in branches:
            if not _admits(branch, "array"):
                kinds = branch.get("type")
                dead_types.extend(kinds if isinstance(kinds, list) else [str(kinds)])
                continue
            if "prefixItems" in branch:
                unverifiable = True
                continue
            items = branch.get("items")
            if isinstance(items, dict) or items is True:
                next_schemas.append(items)
            elif items is None:
                unverifiable = True  # unconstrained array elements
            # items: False (a fixed-length tuple beyond prefixItems) is a
            # dead end handled by contributing nothing.
    return next_schemas, unverifiable, dead_types


def _failure(
    segment: str, prefix: str, declared: tuple[str, ...], detail: str, name: str | None = None
) -> WalkOutcome:
    nearest = None
    if name is not None and declared:
        matches = difflib.get_close_matches(name, declared, n=1)
        nearest = matches[0] if matches else None
    return WalkOutcome(
        status="failed",
        failure=WalkFailure(
            segment=segment, prefix=prefix, declared=declared, nearest=nearest, detail=detail
        ),
    )


def walk_path(compiled: Any, schema: Any) -> WalkOutcome:
    """Resolve a compiled JSONPath query against a JSON Schema declaration.

    Verified: every segment resolves in at least one schema branch.
    Unverified: the expression uses constructs beyond static reach
    (recursive descent, filters, slices), or the schema leaves the shape
    open at some step — visibly passed, never refused. Failed: a segment
    definitively cannot resolve; the outcome carries everything a
    friendly refusal needs.
    """
    schemas: list[Any] = [schema]
    prefix = "$"
    for segment in compiled.segments:
        if not isinstance(segment, JSONPathChildSegment):
            return WalkOutcome(status=UNVERIFIED)  # recursive descent
        for selector in segment.selectors:
            if isinstance(selector, NameSelector):
                name = selector.name
                step = f".{name}"
                next_schemas, open_shape, declared, dead = _descend_name(schemas, name)
                if not next_schemas and not open_shape:
                    if declared:
                        listed = ", ".join(declared)
                        return _failure(
                            name,
                            prefix + step,
                            declared,
                            f"`{name}` names no declared key here (declared: {listed})",
                            name=name,
                        )
                    kinds = ", ".join(dict.fromkeys(dead)) or "non-object"
                    return _failure(
                        name,
                        prefix + step,
                        (),
                        f"`{name}` addresses a value declared as {kinds}, which holds no keys",
                    )
                if not next_schemas:
                    return WalkOutcome(status=UNVERIFIED)
                schemas = next_schemas
                prefix += step
            elif isinstance(selector, (IndexSelector, WildcardSelector)):
                step = f"[{selector.index}]" if isinstance(selector, IndexSelector) else "[*]"
                next_schemas, open_shape, dead = _descend_items(schemas)
                if not next_schemas and not open_shape:
                    kinds = ", ".join(dict.fromkeys(dead)) or "non-array"
                    return _failure(
                        step,
                        prefix + step,
                        (),
                        f"`{step}` indexes into a value declared as {kinds}, which is not an array",
                    )
                if not next_schemas:
                    return WalkOutcome(status=UNVERIFIED)
                schemas = next_schemas
                prefix += step
            else:
                return WalkOutcome(status=UNVERIFIED)  # filter, slice
    return WalkOutcome(status=VERIFIED)


def validate_declared_paths(
    declaration: Any, response_schema: Any, service_name: str
) -> tuple[str, ...]:
    """The path ↔ declared-shape join over a whole contract, at load time.

    Walks every ``path:``-qualified check whose subject view has a declared
    shape — the parsed response (stock ``json`` view) against the service's
    ``response-schema``, a derived view against its transformation's
    declared output schema. Every failing expression is collected first,
    so the refusal itemises them all: the developer sees exactly which
    expressions in which criteria failed, in one message. Returns the
    check verb's fact lines (verified counts per source; one
    ``(unverified)`` line per expression beyond static reach).

    Raises:
        ContractConfigurationError: At least one expression definitively
            cannot resolve; the message names every one.
    """
    from ._parser import RAW_VIEW
    from ._registry import _STOCK_TRANSFORMS, transform_registration
    from ._structured import compile_jsonpath

    entries: list[tuple[str, str, str]] = []  # (context, view, path)
    for criterion in declaration.criteria:
        for ordinal, form in enumerate(criterion.forms, start=1):
            if form.path is not None:
                entries.append(
                    (f"criterion {criterion.name!r}, postcondition {ordinal}", form.view, form.path)
                )
    for input_index, input_value, forms in declaration.expected_pairs:
        for ordinal, form in enumerate(forms, start=1):
            if form.path is not None:
                entries.append(
                    (
                        f"expected for input {input_index} "
                        f"({bounded_excerpt(str(input_value), 64)!r}), form {ordinal}",
                        form.view,
                        form.path,
                    )
                )

    verified: dict[str, int] = {}
    unverified: list[str] = []
    failures: list[str] = []
    for context, view, path in entries:
        if view == RAW_VIEW:
            continue
        transformation = declaration.transforms.get(view)
        if transformation == "json":
            if response_schema is None:
                continue
            schema, source = response_schema, f"response-schema of service {service_name!r}"
        elif transformation in _STOCK_TRANSFORMS:
            continue  # xml/yaml: no JSON Schema join
        else:
            registration = transform_registration(str(transformation))
            if registration.output_schema is None or not path.startswith("$"):
                continue  # undeclared shape, or an XPath (no schema join)
            schema, source = (
                registration.output_schema,
                f"declared output schema of view {view!r}",
            )
        outcome = walk_path(compile_jsonpath(path, context), schema)
        if outcome.status == VERIFIED:
            verified[source] = verified.get(source, 0) + 1
        elif outcome.status == UNVERIFIED:
            unverified.append(
                f"(unverified) path `{path}` ({context}): beyond static reach — "
                "exercised only by live samples"
            )
        else:
            failure = outcome.failure
            assert failure is not None
            hint = f" — did you mean `{failure.nearest}`?" if failure.nearest else ""
            failures.append(
                f"  - {context}, in view {view!r}:\n"
                f"      path: {path}\n"
                f"      at `{failure.prefix}`: {failure.detail}{hint}\n"
                f"      (against the {source})"
            )
    if failures:
        count = len(failures)
        plural = "s" if count > 1 else ""
        raise ContractConfigurationError(
            f"{count} path expression{plural} cannot resolve against the declared "
            "shape — checked before any sample is invoked:\n" + "\n".join(failures)
        )
    facts = [
        f"{count} path expression{'s' if count > 1 else ''} resolve{'s' if count == 1 else ''} "
        f"against the {source}"
        for source, count in verified.items()
    ]
    return (*facts, *unverified)
