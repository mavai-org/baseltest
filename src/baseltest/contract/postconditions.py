"""Postconditions: the checks a criterion applies to each response.

A postcondition receives both the raw response text and the transformed
value (when the criterion declares a transform; otherwise the raw text
again) and reports a result -- pass, or a reasoned failure. Anticipated
negative outcomes travel as data, never as exceptions: an exception escaping
a postcondition is a defect in the check itself and aborts the run.

The string forms here are dependency-free and public: they are the
graduation surface's building blocks. Structured checks over parsed
documents are composed by callers (as further ``Postcondition`` values);
this module neither knows nor cares how a check was built.
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
    """A named check over a response.

    Attributes:
        name: A short label identifying the check in output and failure
            distributions (e.g. ``'contains "hello"'``).
        check: The predicate: ``(raw_response, value_under_judgement) ->
            PostconditionResult``.
    """

    name: str
    check: Callable[[str, Any], PostconditionResult]

    def evaluate(self, raw: str, value: Any) -> PostconditionResult:
        """Apply the check to one response."""
        return self.check(raw, value)


def equals(expected: str) -> Postcondition:
    """The response equals the string exactly."""

    def check(raw: str, _value: Any) -> PostconditionResult:
        if raw == expected:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not equal {expected!r}")

    return Postcondition(name=f"equals {expected!r}", check=check)


def one_of(expected: Sequence[str]) -> Postcondition:
    """The response is any one of the listed strings."""
    allowed = tuple(expected)

    def check(raw: str, _value: Any) -> PostconditionResult:
        if raw in allowed:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response is not one of {list(allowed)!r}")

    return Postcondition(name=f"one-of {list(allowed)!r}", check=check)


def contains(substring: str) -> Postcondition:
    """The response contains the substring."""

    def check(raw: str, _value: Any) -> PostconditionResult:
        if substring in raw:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not contain {substring!r}")

    return Postcondition(name=f'contains "{substring}"', check=check)


def matches(pattern: str) -> Postcondition:
    """The response matches the regular expression (searched, per ``re.search``)."""
    compiled = re.compile(pattern)

    def check(raw: str, _value: Any) -> PostconditionResult:
        if compiled.search(raw) is not None:
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"response does not match /{pattern}/")

    return Postcondition(name=f"matches /{pattern}/", check=check)


def satisfies(name: str, predicate: Callable[[Any], bool]) -> Postcondition:
    """A named check: the predicate holds for the value under judgement.

    The predicate receives the transformed value when the criterion declares
    a transform, and the raw response text otherwise.
    """

    def check(_raw: str, value: Any) -> PostconditionResult:
        if predicate(value):
            return PostconditionResult.ok()
        return PostconditionResult.failed(f"check {name!r} not satisfied")

    return Postcondition(name=name, check=check)
