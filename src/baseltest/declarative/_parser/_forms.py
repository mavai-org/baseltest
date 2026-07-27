"""The postcondition forms: one ``expected:``/criterion form entry, parsed.

The form vocabulary — the string forms (``equals``/``one-of``/``contains``/
``matches``), ``parses``/``satisfies``, and the value-comparison forms
(the numeric sextet ``eq``/``ne``/``lt``/``le``/``gt``/``ge``,
``not-equals``, ``equals-ci``, ``is-null``, and the collective set forms
``equals-set``/``contains-set``/``count-equals``) — with the ``in:`` view
and ``path:`` qualifiers and their legality checks: ``path:`` belongs to
the string and value-comparison forms, and a set form judges a selection
collectively so it requires a declared view and a ``path:``.
"""

import re
from typing import Any

from ._model import RAW_VIEW, Form, FormDeclaration
from ._shape import _fail

_STRING_FORMS = ("equals", "one-of", "contains", "matches")
_NUMERIC_FORMS = ("eq", "ne", "lt", "le", "gt", "ge")
# Scalar value forms: universal over a multi-valued selection, like the
# string forms; path-capable under a declared view.
_SCALAR_VALUE_FORMS = (*_NUMERIC_FORMS, "not-equals", "equals-ci", "is-null")
# Set forms: collective over the selection — they REQUIRE `in:` + `path:`.
_SET_FORMS = ("equals-set", "contains-set", "count-equals")
_PATH_FORMS = (*_STRING_FORMS, *_SCALAR_VALUE_FORMS, *_SET_FORMS)
_FORM_KEYS = (
    "equals",
    "one-of",
    "contains",
    "matches",
    "parses",
    "satisfies",
    *_SCALAR_VALUE_FORMS,
    *_SET_FORMS,
)

_NUMERIC_OPERAND = re.compile(r"^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$")
_SET_ELEMENT_TYPES = (str, int, float, bool, type(None))


def _is_numeric_operand(value: Any) -> bool:
    """A number, or a numeric string (quoting preserves the exact decimal)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    return isinstance(value, str) and bool(_NUMERIC_OPERAND.match(value.strip()))


def _parse_form_entry(entry: dict[str, Any], where: str, views: dict[str, str]) -> FormDeclaration:
    keys = set(entry)
    view = RAW_VIEW
    path = None
    if "in" in keys:
        view_value = entry["in"]
        if not isinstance(view_value, str) or not view_value:
            raise _fail(f"{where}: `in:` must name a view")
        if view_value != RAW_VIEW and view_value not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(
                f"{where}: `in: {view_value}` names an undeclared view "
                f"(declared: {declared}; `raw` is always available)"
            )
        view = view_value
        keys.discard("in")
    if "path" in keys:
        path_value = entry["path"]
        if not isinstance(path_value, str) or not path_value:
            raise _fail(f"{where}: `path:` must be a non-empty string")
        path = path_value
        keys.discard("path")
    if len(keys) != 1:
        raise _fail(f"{where}: each postcondition declares exactly one form")
    form = keys.pop()
    if form not in _FORM_KEYS:
        raise _fail(f"{where}: unknown postcondition form `{form}`")
    argument = entry[form]
    if form == "one-of":
        if (
            not isinstance(argument, list)
            or not argument
            or not all(isinstance(item, str) for item in argument)
        ):
            raise _fail(f"{where}: `one-of:` takes a non-empty list of strings")
    elif form in ("equals", "contains", "matches"):
        if not isinstance(argument, str):
            raise _fail(f"{where}: `{form}:` takes a string")
    elif form == "satisfies" and (not isinstance(argument, str) or not argument):
        raise _fail(f"{where}: `satisfies:` names a check registered in code")
    elif form in _NUMERIC_FORMS:
        if not _is_numeric_operand(argument):
            raise _fail(
                f"{where}: `{form}:` takes a number or a numeric string "
                f"(sign/decimal/exponent), got {argument!r}"
            )
    elif form in ("not-equals", "equals-ci"):
        if not isinstance(argument, str):
            raise _fail(f"{where}: `{form}:` takes a string")
    elif form == "is-null":
        if argument is not True:
            raise _fail(
                f"{where}: `is-null:` takes the literal `true` and nothing else — "
                "the negation is not offered"
            )
    elif form in ("equals-set", "contains-set"):
        if (
            not isinstance(argument, list)
            or not argument
            or not all(isinstance(item, _SET_ELEMENT_TYPES) for item in argument)
        ):
            raise _fail(
                f"{where}: `{form}:` takes a non-empty list of scalar values "
                "(an empty-selection assertion is `count-equals: 0`)"
            )
    elif form == "count-equals" and (
        isinstance(argument, bool) or not isinstance(argument, int) or argument < 0
    ):
        raise _fail(f"{where}: `count-equals:` takes a non-negative integer")
    if path is not None:
        if form not in _PATH_FORMS:
            raise _fail(f"{where}: `path:` qualifies the string and value-comparison forms only")
        if view == RAW_VIEW:
            raise _fail(
                f"{where}: `path:` requires `in:` naming a declared view — "
                "the raw response is unstructured text"
            )
    if form in _SET_FORMS and (path is None or view == RAW_VIEW):
        raise _fail(
            f"{where}: `{form}:` judges the values a path selects, collectively — "
            "it requires `in:` naming a declared view and a `path:` (there is no "
            "collection over the raw text or a scalar)"
        )
    if form == "parses":
        target = entry[form]
        if view != RAW_VIEW:
            raise _fail(f"{where}: `parses:` takes no `in:` — it names its view directly")
        if not isinstance(target, str) or target not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(f"{where}: `parses:` references a declared view (declared: {declared})")
    return FormDeclaration(form=Form(form), argument=entry[form], view=view, path=path)
