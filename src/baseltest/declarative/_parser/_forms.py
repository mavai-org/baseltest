"""The postcondition forms: one ``expected:``/criterion form entry, parsed.

The form vocabulary (``equals``/``one-of``/``contains``/``matches``/
``parses``/``satisfies``), the ``in:`` view and ``path:`` qualifiers, and
the legality checks that only the string forms take a ``path:``.
"""

from typing import Any

from ._model import RAW_VIEW, Form, FormDeclaration
from ._shape import _fail

_FORM_KEYS = ("equals", "one-of", "contains", "matches", "parses", "satisfies")
_STRING_FORMS = ("equals", "one-of", "contains", "matches")


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
    if path is not None:
        if form not in _STRING_FORMS:
            raise _fail(f"{where}: `path:` qualifies the string forms only")
        if view == RAW_VIEW:
            raise _fail(
                f"{where}: `path:` requires `in:` naming a declared view — "
                "the raw response is unstructured text"
            )
    if form == "parses":
        target = entry[form]
        if view != RAW_VIEW:
            raise _fail(f"{where}: `parses:` takes no `in:` — it names its view directly")
        if not isinstance(target, str) or target not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(f"{where}: `parses:` references a declared view (declared: {declared})")
    return FormDeclaration(form=Form(form), argument=entry[form], view=view, path=path)
