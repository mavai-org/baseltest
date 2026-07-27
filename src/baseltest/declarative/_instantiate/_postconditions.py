"""Postconditions and criteria: a declaration's checks made runnable.

The declarative ``expected:``/``forms:`` vocabulary — the string forms
(``equals``, ``contains``, ``matches``, ``one-of``), ``satisfies``,
``parses``, and the value-comparison forms (``eq``/``ne``/``lt``/``le``/
``gt``/``ge``, ``not-equals``, ``equals-ci``, ``is-null``, and the
collective ``equals-set``/``contains-set``/``count-equals``) — is built
into :class:`Postcondition` objects here, scoped per input where the
declaration is per input, and assembled into the :class:`Criterion` the
engine judges.
"""

from collections.abc import Callable, Sequence
from typing import Any

from baseltest.contract import (
    Criterion,
    Postcondition,
    PostconditionResult,
    ThresholdProvenance,
    contains,
    contains_set,
    count_equals,
    eq,
    equals,
    equals_ci,
    equals_set,
    ge,
    gt,
    is_null,
    le,
    lt,
    matches,
    ne,
    not_equals,
    one_of,
    satisfies,
)
from baseltest.engine.naming import bounded_excerpt, per_input_name

from .._parser import RAW_VIEW, CriterionDeclaration, Form, FormDeclaration
from .._registry import Registry
from .._structured import (
    compile_jsonpath,
    compile_xpath,
    path_collective,
    path_each_value,
    path_qualified,
)

_STRING_FORMS: dict[str, Callable[..., Postcondition]] = {
    "equals": lambda arg, view: equals(str(arg), view=view),
    "contains": lambda arg, view: contains(str(arg), view=view),
    "matches": lambda arg, view: matches(str(arg), view=view),
    "one-of": lambda arg, view: one_of([str(item) for item in arg], view=view),
}

# Scalar value-comparison forms: universal over a selection, judging the
# selected value itself (never a text projection — `is-null` distinguishes
# JSON null from the string "null", the numeric forms compare decimals).
_SCALAR_VALUE_FORMS: dict[str, Callable[..., Postcondition]] = {
    "eq": lambda arg, view: eq(arg, view=view),
    "ne": lambda arg, view: ne(arg, view=view),
    "lt": lambda arg, view: lt(arg, view=view),
    "le": lambda arg, view: le(arg, view=view),
    "gt": lambda arg, view: gt(arg, view=view),
    "ge": lambda arg, view: ge(arg, view=view),
    "not-equals": lambda arg, view: not_equals(str(arg), view=view),
    "equals-ci": lambda arg, view: equals_ci(str(arg), view=view),
    "is-null": lambda arg, view: is_null(view=view),
}

# Collective set forms: the whole selection at once. The parser guarantees
# a declared view and a path.
_SET_FORMS: dict[str, Callable[..., Postcondition]] = {
    "equals-set": lambda arg, view: equals_set(list(arg), view=view),
    "contains-set": lambda arg, view: contains_set(list(arg), view=view),
    "count-equals": lambda arg, view: count_equals(int(arg), view=view),
}


def _parses_postcondition(view: str) -> Postcondition:
    """``parses: <view>``: forcing the view's computation is the whole check."""
    return Postcondition(
        name=f"parses as {view}",
        check=lambda _subject: PostconditionResult.ok(),
        view=view,
    )


def _compiled_path(
    path: str, view: str, transforms: dict[str, str], where: str
) -> tuple[str, str, Any, bool]:
    """The path's language, display expression, compiled form, and whether the
    view's value type must be verified per trial.

    A stock transformation pins the language (``json``/``yaml`` → JSONPath,
    ``xml`` → XPath 1.0). A custom transformation names no path language, so
    the expression's syntax decides: RFC 9535 mandates ``$``-rooted JSONPath,
    and a ``$``-initial XPath is a variable reference no contract can bind —
    everything else validates as XPath 1.0. The custom view's value type is
    then checked per trial; load time cannot know what the transform returns.
    """
    transformation = transforms.get(view)
    if transformation in ("json", "yaml"):
        return "jsonpath", path, compile_jsonpath(path, where), False
    if transformation == "xml":
        expression = compile_xpath(path, where)
        return "xpath", expression, expression, False
    if path.startswith("$"):
        return "jsonpath", path, compile_jsonpath(path, where), True
    expression = compile_xpath(path, where)
    return "xpath", expression, expression, True


def _build_form(
    declaration: FormDeclaration, transforms: dict[str, str], where: str, registry: Registry
) -> Postcondition:
    if declaration.form is Form.SATISFIES:
        name = str(declaration.argument)
        return satisfies(name, registry.resolve_check(name), view=declaration.view)
    if declaration.form is Form.PARSES:
        return _parses_postcondition(str(declaration.argument))
    form_key = declaration.form.value
    if form_key in _SET_FORMS:
        # The parser guarantees a declared view and a path — a collection
        # only exists as a selection.
        assert declaration.path is not None
        inner = _SET_FORMS[form_key](declaration.argument, RAW_VIEW)
        language, expression, compiled, check_value_type = _compiled_path(
            declaration.path, declaration.view, transforms, where
        )
        return path_collective(
            language,
            expression,
            compiled,
            inner,
            view=declaration.view,
            check_value_type=check_value_type,
        )
    if form_key in _SCALAR_VALUE_FORMS:
        builder = _SCALAR_VALUE_FORMS[form_key]
        if declaration.path is None:
            return builder(declaration.argument, declaration.view)
        inner = builder(declaration.argument, RAW_VIEW)
        language, expression, compiled, check_value_type = _compiled_path(
            declaration.path, declaration.view, transforms, where
        )
        return path_each_value(
            language,
            expression,
            compiled,
            inner,
            view=declaration.view,
            check_value_type=check_value_type,
            # is-null is null-or-absent: a path that selects nothing holds.
            empty_selection_holds=declaration.form is Form.IS_NULL,
        )
    builder = _STRING_FORMS[declaration.form]
    if declaration.path is None:
        return builder(declaration.argument, declaration.view)
    inner = builder(declaration.argument, RAW_VIEW)
    language, expression, compiled, check_value_type = _compiled_path(
        declaration.path, declaration.view, transforms, where
    )
    return path_qualified(
        language,
        expression,
        compiled,
        inner,
        view=declaration.view,
        check_value_type=check_value_type,
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
