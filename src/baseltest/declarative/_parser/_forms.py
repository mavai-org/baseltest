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

import math
import re
import sys
from decimal import Decimal
from typing import Any

from ._model import RAW_VIEW, Form, FormDeclaration
from ._shape import _fail

_STRING_FORMS = ("equals", "one-of", "contains", "matches")
_NUMERIC_FORMS = ("eq", "ne", "lt", "le", "gt", "ge")
# Scalar value forms: universal over a multi-valued selection, like the
# string forms; path-capable under a declared view.
_SCALAR_VALUE_FORMS = (*_NUMERIC_FORMS, "not-equals", "equals-ci", "is-null", "is")
# Set forms: collective over the selection — they REQUIRE `in:` + `path:`.
_SET_FORMS = ("equals-set", "contains-set", "count-equals", "set-of")
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
_SET_OF_KEYS = ("required", "optional", "min-present", "refuse-extras")
_PERCENT_MIN_PRESENT = re.compile(r"^([0-9]+(?:\.[0-9]+)?)%$")


def _is_numeric_operand(value: Any) -> bool:
    """A number, or a numeric string (quoting preserves the exact decimal)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    return isinstance(value, str) and bool(_NUMERIC_OPERAND.match(value.strip()))


def _parse_form_entry(entry: dict[str, Any], where: str, views: dict[str, str]) -> FormDeclaration:
    keys = set(entry)
    view: str | None = RAW_VIEW
    explicit_in = "in" in keys
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
    optional = False
    if "optional" in keys:
        if entry["optional"] is not True:
            raise _fail(
                f"{where}: `optional:` takes the literal `true` and nothing else — "
                "required is the default, not a spelling"
            )
        optional = True
        keys.discard("optional")
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
            # The guiding refusal (boolean amendment, 2026-07-27): the
            # intuitive-but-refused spellings name the form that expresses
            # the intent, instead of stranding the author at the type rule.
            if form == "equals" and isinstance(argument, bool):
                raise _fail(
                    f"{where}: `equals:` takes a string — a boolean field is "
                    "judged with `is: true` / `is: false`"
                )
            if form == "equals" and argument is None:
                raise _fail(
                    f"{where}: `equals:` takes a string — a null expectation is `is-null: true`"
                )
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
    elif form == "is":
        if not isinstance(argument, bool):
            raise _fail(
                f"{where}: `is:` takes a boolean — it judges JSON true/false by "
                f"identity, and the string projections belong to `equals:`; got "
                f"{argument!r}"
            )
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
    elif form == "set-of":
        argument = _parse_set_of(argument, where)
    if path is not None:
        if form not in _PATH_FORMS:
            raise _fail(f"{where}: `path:` qualifies the string and value-comparison forms only")
        if explicit_in and view == RAW_VIEW:
            raise _fail(
                f"{where}: `path:` cannot target `raw` — the raw response is "
                "unstructured text; name a declared view with `in:`"
            )
        if not explicit_in:
            # The path-conditional default (subject rule, 2026-07-27): a
            # path-bearing form omitting `in:` unambiguously wants a
            # structured view — the parser resolves it against the owning
            # criterion once all its forms are known.
            view = None
    if form in _SET_FORMS and (path is None or (explicit_in and view == RAW_VIEW)):
        raise _fail(
            f"{where}: `{form}:` judges the values a path selects, collectively — "
            "it requires a `path:` under a declared view (there is no "
            "collection over the raw text or a scalar)"
        )
    if form == "parses":
        target = entry[form]
        if view != RAW_VIEW:
            raise _fail(f"{where}: `parses:` takes no `in:` — it names its view directly")
        if optional:
            raise _fail(
                f"{where}: `optional:` on `parses:` is refused — a transform failure "
                "hard-fails the trial regardless of any optional-slack budget, so "
                "the mark would be inert"
            )
        if not isinstance(target, str) or target not in views:
            declared = ", ".join(sorted(views)) or "none declared"
            raise _fail(f"{where}: `parses:` references a declared view (declared: {declared})")
    return FormDeclaration(
        form=Form(form), argument=argument, view=view, path=path, optional=optional
    )


def _parse_set_of(argument: Any, where: str) -> dict[str, Any]:
    """The composite graded set claim, normalised: membership semantics — a set
    is a set. Duplicates in a declared list collapse to one entry with a
    console warning (most likely an authoring typo), never a refusal; every
    contradiction and unsatisfiable or saturated floor refuses at load; a
    spelling a sharper form owns is refused naming that form."""
    if not isinstance(argument, dict):
        raise _fail(
            f"{where}: `set-of:` takes a mapping — required:/optional: member "
            "lists, min-present:, refuse-extras:"
        )
    for key in argument:
        if key not in _SET_OF_KEYS:
            raise _fail(
                f"{where}: `set-of:` has unknown key `{key}:` — its keys are "
                f"{', '.join(_SET_OF_KEYS)}"
            )
    required = _member_list(argument, "required", where)
    optional = _member_list(argument, "optional", where)
    if not required and not optional:
        raise _fail(
            f"{where}: `set-of:` states nothing — declare `required:` and/or `optional:` members"
        )
    refuse_extras = argument.get("refuse-extras", True)
    if not isinstance(refuse_extras, bool):
        raise _fail(f"{where}: `refuse-extras:` takes a boolean")
    if not optional:
        # A sharper name for the stated claim exists — refuse and name it.
        sharper = "equals-set" if refuse_extras else "contains-set"
        raise _fail(
            f"{where}: a `set-of:` without `optional:` members states `{sharper}:` — say that"
        )
    min_present = _min_present(argument.get("min-present"), len(optional), where)
    if min_present > len(optional):
        raise _fail(
            f"{where}: `min-present: {argument['min-present']}` exceeds "
            f"the `optional:` list's distinct size ({len(optional)})"
        )
    if min_present == len(optional):
        raise _fail(
            f"{where}: `min-present: {argument['min-present']}` equals "
            f"the `optional:` list's distinct size ({len(optional)}) — every "
            "optional member is required; move them to `required:`"
        )
    optional_keys = {_member_key(member) for member in optional}
    overlap = [member for member in required if _member_key(member) in optional_keys]
    if overlap:
        raise _fail(
            f"{where}: {overlap[0]!r} appears in both `required:` and "
            "`optional:` — a member is one or the other"
        )
    return {
        "required": required,
        "optional": optional,
        "min-present": min_present,
        "refuse-extras": refuse_extras,
    }


def _member_list(argument: dict[str, Any], name: str, where: str) -> list[Any]:
    """One declared member list as a set: order kept, duplicates collapsed
    with a console warning."""
    value = argument.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not value:
        raise _fail(f"{where}: `set-of:` `{name}:` takes a non-empty list of scalar values")
    if not all(isinstance(item, _SET_ELEMENT_TYPES) for item in value):
        raise _fail(f"{where}: `set-of:` `{name}:` takes a non-empty list of scalar values")
    members: list[Any] = []
    seen: set[tuple[str, Any]] = set()
    for item in value:
        key = _member_key(item)
        if key in seen:
            print(
                f"warning: {where}: `set-of:` `{name}:` lists {item!r} more than "
                "once — duplicates collapse to one entry (likely a typo)",
                file=sys.stderr,
            )
        else:
            seen.add(key)
            members.append(item)
    return members


def _member_key(item: Any) -> tuple[str, Any]:
    """A member under strict JSON-value equality: numbers numerically
    (decimal), strings exactly, booleans and null by identity — a number
    never equals its string spelling, and JSON true never equals 1."""
    if isinstance(item, bool):
        return ("bool", item)
    if isinstance(item, int | float):
        return ("num", Decimal(str(item)))
    if item is None:
        return ("null", None)
    return ("str", item)


def _min_present(value: Any, optional_size: int, where: str) -> int:
    """The floor over the optional list: a distinct-member count, or an
    explicit percentage resolved by floor (the % suffix is the
    disambiguator, exactly as `optional-slack:`)."""
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str):
        match = _PERCENT_MIN_PRESENT.match(value.strip())
        if match:
            return math.floor(float(match.group(1)) / 100 * optional_size)
    raise _fail(
        f"{where}: `min-present:` takes a non-negative whole count of distinct "
        f"optional members, or an explicit percentage like `80%` — got {value!r} "
        "(a bare fraction is never guessed at)"
    )
