"""Postconditions: the checks a criterion applies to each response.

Every postcondition judges exactly one **view** of the response, named by
its ``view`` attribute; the default subject is ``"raw"`` — the
untransformed response text. Checks report a result — pass, or a reasoned
failure — and anticipated negative outcomes travel as data, never as
exceptions: an exception escaping a check is a defect in the check itself
and aborts the run.

The string forms here are dependency-free and public: they are the
graduation surface's building blocks. They require a text subject; judging
a non-text view value with a string form is a per-trial type failure, not
an error.
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class PostconditionResult:
    """The outcome of one postcondition against one response.

    Attributes:
        passed: Whether the check held.
        reason: A short human-readable reason when it did not, used in
            failure-distribution reporting; ``None`` on a pass.
        obtained: What the check actually found where it looked — the value
            selected by a path-addressed check, reported by the check
            because it is the only party that performed the projection.
            ``None`` when the check is not path-addressed, in which case the
            subject it judged is the value.
        no_value_at_path: The path selected nothing. Distinct from finding a
            different value: a missing field and a wrong extraction are
            different defects, and a reader must be able to tell them apart
            without inferring it from an absent excerpt.
    """

    passed: bool
    reason: str | None = None
    obtained: Any | None = None
    no_value_at_path: bool = False

    @staticmethod
    def ok() -> "PostconditionResult":
        """A passing result."""
        return PostconditionResult(passed=True)

    @staticmethod
    def failed(reason: str) -> "PostconditionResult":
        """A failing result carrying its reason."""
        return PostconditionResult(passed=False, reason=reason)


@dataclass(frozen=True, slots=True)
class Postcondition:
    """A named check over one view of the response.

    Attributes:
        name: A short label identifying the check in output and failure
            distributions (e.g. ``'contains "hello"'``).
        check: The predicate over the subject: ``(subject) ->
            PostconditionResult``.
        view: The name of the view the check judges; ``"raw"`` (the
            untransformed response) by default.
        applies_to_input: For a per-input expectation, the index of the
            input this check judges — the selection tag a criterion reads to
            decide which of its checks a sample driven by that input is
            judged against (:meth:`Criterion.postconditions_for`). A check
            reaches ``evaluate`` only on the samples it applies to; it is
            never asked to judge a sample it does not belong to. ``None``
            (the default) means the check applies to every input.
        required: Whether the check is non-negotiable (the default). An
            optional check's failure counts against its criterion's
            optional-slack budget instead of failing the trial outright —
            partial credit is a double opt-in: marking a check optional
            weakens nothing until the criterion also declares a budget.
    """

    name: str
    check: Callable[[Any], PostconditionResult]
    view: str = "raw"
    applies_to_input: int | None = None
    required: bool = True
    path: str | None = None
    form: str | None = None
    expected: str | None = None

    def evaluate(self, subject: Any) -> PostconditionResult:
        """Apply the check to the resolved subject.

        The caller selects which checks a sample is judged against before
        evaluation (a per-input expectation reaches here only on the samples
        it applies to), so this simply runs the check — there is no
        applicability gate to re-litigate.
        """
        return self.check(subject)


def _text(subject: Any) -> str | None:
    """The text a string form judges, or None (type failure) for non-text."""
    return subject if isinstance(subject, str) else None


def _type_failure(form: str, subject: Any) -> PostconditionResult:
    return PostconditionResult.failed(
        f"{form}: subject is {type(subject).__name__}, not text — a string form judges text"
    )


def equals(expected: str, view: str = "raw") -> Postcondition:
    """The subject equals the string exactly."""

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("equals", subject)
        if text == expected:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not equal {expected!r}")

    return Postcondition(
        name=f"equals {expected!r}", check=check, view=view, form="equals", expected=str(expected)
    )


def one_of(expected: Sequence[str], view: str = "raw") -> Postcondition:
    """The subject is any one of the listed strings."""
    allowed = tuple(expected)

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("one-of", subject)
        if text in allowed:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response is not one of {list(allowed)!r}")

    return Postcondition(
        name=f"one-of {list(allowed)!r}",
        check=check,
        view=view,
        form="one-of",
        expected=str(list(allowed)),
    )


def contains(substring: str, view: str = "raw") -> Postcondition:
    """The subject contains the substring."""

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("contains", subject)
        if substring in text:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not contain {substring!r}")

    return Postcondition(
        name=f'contains "{substring}"', check=check, view=view, form="contains", expected=substring
    )


def matches(pattern: str, view: str = "raw") -> Postcondition:
    """The subject matches the regular expression (searched, per ``re.search``)."""
    compiled = re.compile(pattern)

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("matches", subject)
        if compiled.search(text) is not None:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not match /{pattern}/")

    return Postcondition(
        name=f"matches /{pattern}/", check=check, view=view, form="matches", expected=pattern
    )


def satisfies(name: str, predicate: Callable[[Any], bool], view: str = "raw") -> Postcondition:
    """A named check: the predicate holds for the subject view's value."""

    def check(subject: Any) -> PostconditionResult:
        if predicate(subject):
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"check {name!r} not satisfied")

    return Postcondition(name=name, check=check, view=view)


# ── The value-comparison forms ─────────────────────────────────────────
#
# These judge typed values, not text: a number by decimal comparison, a
# selection by strict JSON-value equality. The scalar forms judge one
# subject (fanned across a multi-valued selection by the caller, like the
# string forms); the collective forms judge a whole selection at once, so
# their subject is the sequence of selected values.

_NUMERIC_PATTERN = re.compile(r"^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$")


def _decimal(value: Any) -> Decimal | None:
    """The subject or operand as an exact decimal; None when uninterpretable.

    A number (never a boolean) or a numeric string qualifies; comparison is
    decimal, not binary float, so formatting differences (``2637.80`` vs
    ``2.6378e3``) and float artefacts never decide a verdict.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str) and _NUMERIC_PATTERN.match(value.strip()):
        return Decimal(value.strip())
    return None


def _numeric_type_failure(form: str, subject: Any) -> PostconditionResult:
    return PostconditionResult.failed(
        f"{form}: subject {subject!r} ({type(subject).__name__}) is not a number — "
        "a numeric form judges a number or a numeric string"
    )


def _numeric_form(
    form: str, operand: Any, holds: Callable[[Decimal, Decimal], bool], view: str
) -> Postcondition:
    expected = _decimal(operand)
    if expected is None:
        raise ValueError(f"{form}: operand {operand!r} is not a number or numeric string")

    def check(subject: Any) -> PostconditionResult:
        actual = _decimal(subject)
        if actual is None:
            return _numeric_type_failure(form, subject)
        if holds(actual, expected):
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"value {subject!r} is not {form} {operand!r}")

    return Postcondition(
        name=f"{form} {operand!r}", check=check, view=view, form=form, expected=str(operand)
    )


def eq(operand: Any, view: str = "raw") -> Postcondition:
    """The subject equals the operand numerically — formatting-insensitive, decimal."""
    return _numeric_form("eq", operand, lambda a, e: a == e, view)


def ne(operand: Any, view: str = "raw") -> Postcondition:
    """The subject does not equal the operand numerically."""
    return _numeric_form("ne", operand, lambda a, e: a != e, view)


def lt(operand: Any, view: str = "raw") -> Postcondition:
    """The subject is strictly less than the operand."""
    return _numeric_form("lt", operand, lambda a, e: a < e, view)


def le(operand: Any, view: str = "raw") -> Postcondition:
    """The subject is at most the operand."""
    return _numeric_form("le", operand, lambda a, e: a <= e, view)


def gt(operand: Any, view: str = "raw") -> Postcondition:
    """The subject is strictly greater than the operand."""
    return _numeric_form("gt", operand, lambda a, e: a > e, view)


def ge(operand: Any, view: str = "raw") -> Postcondition:
    """The subject is at least the operand."""
    return _numeric_form("ge", operand, lambda a, e: a >= e, view)


def not_equals(expected: str, view: str = "raw") -> Postcondition:
    """The subject does not equal the string exactly."""

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("not-equals", subject)
        if text != expected:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response equals the excluded {expected!r}")

    return Postcondition(
        name=f"not-equals {expected!r}",
        check=check,
        view=view,
        form="not-equals",
        expected=expected,
    )


def _folded(text: str) -> str:
    """The equals-ci normalisation, exactly: Unicode case-fold, trim, and
    internal-whitespace-run collapse to a single space — nothing more."""
    return " ".join(text.casefold().split())


def equals_ci(expected: str, view: str = "raw") -> Postcondition:
    """The subject equals the string after case-fold and whitespace normalisation."""
    folded_expected = _folded(expected)

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("equals-ci", subject)
        if _folded(text) == folded_expected:
            return PostconditionResult.ok()
        return PostconditionResult.failed(
            f"response does not equal {expected!r} (case/whitespace-insensitively)"
        )

    return Postcondition(
        name=f"equals-ci {expected!r}", check=check, view=view, form="equals-ci", expected=expected
    )


def is_null(view: str = "raw") -> Postcondition:
    """The subject is JSON ``null`` — distinct from the string ``"null"``.

    The absent half of null-or-absent (a path that selected nothing) is the
    selection machinery's to decide; this form judges the value it is given.
    """

    def check(subject: Any) -> PostconditionResult:
        if subject is None:
            return PostconditionResult.ok()
        return PostconditionResult.failed(
            f"value {subject!r} ({type(subject).__name__}) is not null"
        )

    return Postcondition(name="is-null", check=check, view=view, form="is-null")


def is_(operand: bool, view: str = "raw") -> Postcondition:
    """The subject is JSON ``true``/``false`` **by identity** — never the
    strings ``"true"``/``"false"`` or the numbers 1/0."""

    def check(subject: Any) -> PostconditionResult:
        if isinstance(subject, bool):
            if subject == operand:
                return PostconditionResult.ok()
            return PostconditionResult.failed(f"value is {subject}, not {operand}")
        return PostconditionResult.failed(
            f"is: subject {subject!r} ({type(subject).__name__}) is not a boolean — "
            "the form judges JSON true/false by identity"
        )

    return Postcondition(
        name=f"is {operand}", check=check, view=view, form="is", expected=str(operand).lower()
    )


def _element_key(value: Any) -> tuple[str, Any]:
    """A selected or operand element under strict JSON-value equality.

    Numbers compare numerically (decimal), strings exactly, booleans and
    null by identity; a number never equals its string spelling.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int | float):
        return ("num", _decimal(value))
    if value is None:
        return ("null", None)
    return ("str", value)


def _selection(subject: Any) -> list[Any] | None:
    """The selection a collective form judges, or None (type failure)."""
    if isinstance(subject, Sequence) and not isinstance(subject, str | bytes):
        return list(subject)
    return None


def _collective_type_failure(form: str, subject: Any) -> PostconditionResult:
    return PostconditionResult.failed(
        f"{form}: subject is {type(subject).__name__}, not a selection — a set "
        "form judges the values a path selects, collectively"
    )


def equals_set(expected: Sequence[Any], view: str = "raw") -> Postcondition:
    """The selection equals the operand as a multiset — order-independent,
    duplicates significant."""
    expected_counts = Counter(_element_key(item) for item in expected)
    operand = list(expected)

    def check(subject: Any) -> PostconditionResult:
        selected = _selection(subject)
        if selected is None:
            return _collective_type_failure("equals-set", subject)
        if Counter(_element_key(item) for item in selected) == expected_counts:
            return PostconditionResult.ok()
        return PostconditionResult.failed(
            f"selected values {selected!r} do not equal {operand!r} as a multiset"
        )

    return Postcondition(
        name=f"equals-set {operand!r}",
        check=check,
        view=view,
        form="equals-set",
        expected=str(operand),
    )


def contains_set(expected: Sequence[Any], view: str = "raw") -> Postcondition:
    """Every operand element appears among the selection (all-of, with
    multiplicity)."""
    expected_counts = Counter(_element_key(item) for item in expected)
    operand = list(expected)

    def check(subject: Any) -> PostconditionResult:
        selected = _selection(subject)
        if selected is None:
            return _collective_type_failure("contains-set", subject)
        missing = expected_counts - Counter(_element_key(item) for item in selected)
        if not missing:
            return PostconditionResult.ok()
        return PostconditionResult.failed(
            f"selected values {selected!r} do not contain all of {operand!r}"
        )

    return Postcondition(
        name=f"contains-set {operand!r}",
        check=check,
        view=view,
        form="contains-set",
        expected=str(operand),
    )


def _member_display(values: Sequence[Any], limit: int = 3) -> str:
    """A bounded member listing for reasons: the first few, the rest counted."""
    shown = ", ".join(repr(value) for value in values[:limit])
    remainder = len(values) - limit
    return shown if remainder <= 0 else f"{shown} (+{remainder} more)"


def set_of(
    required: Sequence[Any],
    optional: Sequence[Any],
    min_present: int = 0,
    refuse_extras: bool = True,
    view: str = "raw",
) -> Postcondition:
    """The graded set claim, judged by membership — a set is a set.

    Holds iff every ``required`` member appears in the selection, at least
    ``min_present`` distinct ``optional`` members appear, and — under
    ``refuse_extras`` — every selected element is a declared member.
    Duplicates collapse to membership on both sides: a subject element
    appearing twice is one member present, never an extra. The failure
    reason states the arithmetic — the missing required members, the
    present-versus-floor count, and any extras — each list bounded.
    """
    required_members = list(required)
    optional_members = list(optional)
    required_keys = {_element_key(item): item for item in required_members}
    optional_keys = {_element_key(item): item for item in optional_members}

    def check(subject: Any) -> PostconditionResult:
        selected = _selection(subject)
        if selected is None:
            return _collective_type_failure("set-of", subject)
        selected_keys: dict[tuple[str, Any], Any] = {}
        for value in selected:
            selected_keys.setdefault(_element_key(value), value)
        missing = [item for key, item in required_keys.items() if key not in selected_keys]
        present = sum(1 for key in optional_keys if key in selected_keys)
        extras = [
            value
            for key, value in selected_keys.items()
            if key not in required_keys and key not in optional_keys
        ]
        parts = []
        if missing:
            parts.append(f"missing required: {_member_display(missing)}")
        if present < min_present:
            parts.append(
                f"optional members present {present} of {len(optional_members)} "
                f"(min-present {min_present})"
            )
        if refuse_extras and extras:
            parts.append(f"extras: {_member_display(extras)}")
        if not parts:
            return PostconditionResult.ok()
        return PostconditionResult.failed("set-of: " + "; ".join(parts))

    summary = (
        f"{len(required_members)} required, {len(optional_members)} optional, "
        f"min-present {min_present}" + ("" if refuse_extras else ", extras allowed")
    )
    return Postcondition(
        name=f"set-of ({summary})",
        check=check,
        view=view,
        form="set-of",
        expected=summary,
    )


def count_equals(expected: int, view: str = "raw") -> Postcondition:
    """The selection holds exactly the expected number of values."""

    def check(subject: Any) -> PostconditionResult:
        selected = _selection(subject)
        if selected is None:
            return _collective_type_failure("count-equals", subject)
        if len(selected) == expected:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"path selected {len(selected)} value(s), not {expected}")

    return Postcondition(
        name=f"count-equals {expected}",
        check=check,
        view=view,
        form="count-equals",
        expected=str(expected),
    )
