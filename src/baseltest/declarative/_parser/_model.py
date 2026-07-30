"""The contract declaration model and the format's identifying constants.

Pure data — the four declaration dataclasses the parser produces, the
postcondition ``Form`` enum, and the format identifier and reserved
``raw`` view name.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from baseltest.engine import Intent

from .._roots import RootDisclosure

FORMAT_IDENTIFIER = "mavai-contract/1"
RAW_VIEW = "raw"


class Form(StrEnum):
    """A postcondition's form — the single key an author writes under a clause."""

    EQUALS = "equals"
    ONE_OF = "one-of"
    CONTAINS = "contains"
    MATCHES = "matches"
    PARSES = "parses"
    SATISFIES = "satisfies"
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    NOT_EQUALS = "not-equals"
    EQUALS_CI = "equals-ci"
    IS_NULL = "is-null"
    IS = "is"
    EQUALS_SET = "equals-set"
    CONTAINS_SET = "contains-set"
    COUNT_EQUALS = "count-equals"
    SET_OF = "set-of"


@dataclass(frozen=True, slots=True)
class FormDeclaration:
    """One postcondition form as declared: form key, argument, subject view, path.

    ``view`` is ``None`` for a ``path:``-bearing form that omitted ``in:`` —
    the subject awaits the path-conditional default resolution against its
    owning criterion (single ``parses:`` view, else the sole declared
    transform, else a load refusal). The parser resolves every subject
    before the declaration leaves it; instantiation never sees ``None``.
    """

    form: Form
    argument: Any
    view: str | None = RAW_VIEW
    path: str | None = None
    # Partial credit: `optional: true` opts the check out of
    # non-negotiability, relaxable within the criterion's optional-slack
    # budget. Required is the default, not a spelling.
    optional: bool = False


@dataclass(frozen=True, slots=True)
class CriterionDeclaration:
    """One criterion entry as declared in the file.

    ``tolerate`` is an empirical criterion's sizing claim: the worst
    acceptable true pass rate, versioned with the claim it protects. It
    feeds risk-driven run sizing at test time and is meaningless alongside
    a declared ``threshold`` (a stipulated bar carries no baseline claim).
    ``confidence`` overrides the contract-level confidence for this
    criterion's derivation and judgement. ``optional_slack`` is the
    partial-credit failure budget for the criterion's optional checks: a
    non-negative count, or a percentage carried as its exact decimal (the
    ``%`` spelling), resolved by floor at evaluation time.
    """

    name: str
    forms: tuple[FormDeclaration, ...]
    threshold: float | None
    threshold_origin: str | None
    contract_ref: str | None
    tolerate: float | None = None
    confidence: float | None = None
    optional_slack: int | Decimal | None = None


@dataclass(frozen=True, slots=True)
class LatencyDeclaration:
    """The contract's ``latency:`` block as declared.

    Exactly one of ``ceilings`` / ``empirical`` is populated: explicit
    per-percentile millisecond ceilings, or the percentiles whose bounds
    are derived from a measured baseline at test time.
    """

    ceilings: tuple[tuple[str, int], ...]
    empirical: tuple[str, ...]
    confidence: float | None
    threshold_origin: str | None
    contract_ref: str | None


@dataclass(frozen=True, slots=True)
class ContractDeclaration:
    """The whole contract file, structurally validated. Posture-free by design."""

    contract: str
    service: str
    transforms: dict[str, str]
    inputs: tuple[Any, ...]
    expected_pairs: tuple[tuple[int, Any, tuple[FormDeclaration, ...]], ...]
    criteria: tuple[CriterionDeclaration, ...]
    intent: Intent
    confidence: float
    latency: LatencyDeclaration | None = None
    # The declared roots, as provenance discloses them (declared value +
    # overridden flag — never a resolved machine-local path).
    roots: tuple["RootDisclosure", ...] = field(default=(), compare=False)
    source_path: Path | None = field(default=None, compare=False)
    # Whether the file itself declared `confidence:` (as opposed to the
    # default applying) — interactive sizing asks only for what is missing.
    confidence_declared: bool = field(default=False, compare=False)
