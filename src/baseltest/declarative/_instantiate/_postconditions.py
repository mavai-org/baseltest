"""Postconditions and criteria: a declaration's checks made runnable.

The declarative ``expected:``/``forms:`` vocabulary (``equals``,
``contains``, ``matches``, ``one-of``, ``satisfies``, ``parses``) is
built into :class:`Postcondition` objects here, scoped per input where
the declaration is per input, and assembled into the :class:`Criterion`
the engine judges.
"""

from collections.abc import Callable, Sequence
from typing import Any

from baseltest.contract import (
    Criterion,
    Postcondition,
    PostconditionResult,
    ThresholdProvenance,
    contains,
    equals,
    matches,
    one_of,
    satisfies,
)
from baseltest.engine.naming import bounded_excerpt, per_input_name

from .._parser import RAW_VIEW, CriterionDeclaration, Form, FormDeclaration
from .._registry import Registry
from .._structured import compile_jsonpath, compile_xpath, path_qualified

_STRING_FORMS: dict[str, Callable[..., Postcondition]] = {
    "equals": lambda arg, view: equals(str(arg), view=view),
    "contains": lambda arg, view: contains(str(arg), view=view),
    "matches": lambda arg, view: matches(str(arg), view=view),
    "one-of": lambda arg, view: one_of([str(item) for item in arg], view=view),
}


def _parses_postcondition(view: str) -> Postcondition:
    """``parses: <view>``: forcing the view's computation is the whole check."""
    return Postcondition(
        name=f"parses as {view}",
        check=lambda _subject: PostconditionResult.ok(),
        view=view,
    )


def _build_form(
    declaration: FormDeclaration, transforms: dict[str, str], where: str, registry: Registry
) -> Postcondition:
    if declaration.form is Form.SATISFIES:
        name = str(declaration.argument)
        return satisfies(name, registry.resolve_check(name), view=declaration.view)
    if declaration.form is Form.PARSES:
        return _parses_postcondition(str(declaration.argument))
    builder = _STRING_FORMS[declaration.form]
    if declaration.path is None:
        return builder(declaration.argument, declaration.view)
    inner = builder(declaration.argument, RAW_VIEW)
    transformation = transforms.get(declaration.view)
    if transformation in ("json", "yaml"):
        compiled = compile_jsonpath(declaration.path, where)
        return path_qualified("jsonpath", declaration.path, compiled, inner, view=declaration.view)
    if transformation == "xml":
        expression = compile_xpath(declaration.path, where)
        return path_qualified("xpath", expression, expression, inner, view=declaration.view)
    # A custom transformation names no path language, so the expression's
    # syntax decides: RFC 9535 mandates `$`-rooted JSONPath, and a
    # `$`-initial XPath is a variable reference no contract can bind —
    # everything else validates as XPath 1.0. The value's type is then
    # checked per trial; load time cannot know what the transform returns.
    if declaration.path.startswith("$"):
        compiled = compile_jsonpath(declaration.path, where)
        return path_qualified(
            "jsonpath",
            declaration.path,
            compiled,
            inner,
            view=declaration.view,
            check_value_type=True,
        )
    expression = compile_xpath(declaration.path, where)
    return path_qualified(
        "xpath", expression, expression, inner, view=declaration.view, check_value_type=True
    )


def _expected_postconditions(
    pairs: Sequence[tuple[int, Any, tuple[FormDeclaration, ...]]],
    transforms: dict[str, str],
    registry: Registry,
) -> list[Postcondition]:
    """Per-input expectations: each check applies only to its own input."""
    dispatching: list[Postcondition] = []
    for input_index, input_value, declarations in pairs:
        for declaration in declarations:
            where = f"expected for input {input_index} ({bounded_excerpt(str(input_value), 64)!r})"
            inner = _build_form(declaration, transforms, where, registry)
            dispatching.append(_dispatch_on_input(input_index, inner))
    return dispatching


def _dispatch_on_input(input_index: int, inner: Postcondition) -> Postcondition:
    """A per-input expectation: the inner check scoped to one input.

    Scoping is declarative — ``applies_to_input`` carries the index, and the
    engine gates on the trial's own input index — so nothing here reads shared
    run state, and inputs with equal values are never conflated.
    """

    def check(subject: Any) -> PostconditionResult:
        result = inner.check(subject)
        if result.passed:
            return result
        # Attribute the failure to its input structurally: identities and
        # reasons carry the input's position, never its text — reasons
        # become artefact mapping keys downstream, and the key discipline
        # forbids input-derived key content (the input list is the
        # developer's own; the index is the reference).
        reason = result.reason or f"postcondition {inner.name!r} not satisfied"
        return PostconditionResult.failed(f"input {input_index}: {reason}")

    return Postcondition(
        name=per_input_name(inner.name, input_index),
        check=check,
        view=inner.view,
        applies_to_input=input_index,
    )


def _build_criterion(
    declaration: CriterionDeclaration,
    confidence: float,
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
    registry: Registry,
) -> Criterion:
    where = f"criterion {declaration.name}"
    postconditions = [_build_form(form, transforms, where, registry) for form in declaration.forms]
    postconditions.extend(expected)
    provenance = ThresholdProvenance(
        origin=declaration.threshold_origin or "unspecified",
        contract_ref=declaration.contract_ref,
    )
    return Criterion(
        name=declaration.name,
        postconditions=tuple(postconditions),
        threshold=declaration.threshold,
        # A criterion-level `confidence:` overrides the contract-level one.
        confidence=declaration.confidence if declaration.confidence is not None else confidence,
        provenance=provenance,
    )
