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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PostconditionResult:
    """The outcome of one postcondition against one response.

    Attributes:
        passed: Whether the check held.
        reason: A short human-readable reason when it did not, used in
            failure-distribution reporting; ``None`` on a pass.
    """

    passed: bool
    reason: str | None = None

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
            input this check judges; the trial's own input index gates it,
            so on any other input the check trivially passes. ``None`` (the
            default) means the check applies to every input.
    """

    name: str
    check: Callable[[Any], PostconditionResult]
    view: str = "raw"
    applies_to_input: int | None = None

    def evaluate(self, subject: Any, input_index: int) -> PostconditionResult:
        """Apply the check to the resolved subject, gated on the driving input.

        A per-input expectation (``applies_to_input`` set) is judged only on
        its own input; on any other it passes without running the check.
        """
        if self.applies_to_input is not None and self.applies_to_input != input_index:
            return PostconditionResult.ok()
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

    return Postcondition(name=f"equals {expected!r}", check=check, view=view)


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

    return Postcondition(name=f"one-of {list(allowed)!r}", check=check, view=view)


def contains(substring: str, view: str = "raw") -> Postcondition:
    """The subject contains the substring."""

    def check(subject: Any) -> PostconditionResult:
        text = _text(subject)
        if text is None:
            return _type_failure("contains", subject)
        if substring in text:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not contain {substring!r}")

    return Postcondition(name=f'contains "{substring}"', check=check, view=view)


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

    return Postcondition(name=f"matches /{pattern}/", check=check, view=view)


def satisfies(name: str, predicate: Callable[[Any], bool], view: str = "raw") -> Postcondition:
    """A named check: the predicate holds for the subject view's value."""

    def check(subject: Any) -> PostconditionResult:
        if predicate(subject):
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"check {name!r} not satisfied")

    return Postcondition(name=name, check=check, view=view)
