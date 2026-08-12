"""Pooling one iteration's postcondition standings into stepper evidence.

The run already computes, per ``(input, check)``, everything a tuner needs
to know about a failure — which check, of which form, at which path, what
was expected, what was obtained, and whether the criterion or the input
declared it. This module pools those rows into the shapes a stepper
reasons about, so that a stepper receives *facts about the service* rather
than a table of rows to re-derive them from.

The pooling key is ``(provenance, form, path)``. That is the lattice this
codebase can actually offer: ``covariates`` here name a *service
configuration's* identity, not per-input strata, so there is no input
covariate to group on — and for the deviation-shape question the
comparison form is the better key anyway.

Pooling is also what makes input-declared evidence usable without
memorising answers. An input-declared check is ``n = 1`` by construction;
nine of them missing the same way is one statement about the service, and
a group carries only *how many* inputs it covered, never which.
"""

from collections.abc import Sequence

from baseltest.contract.evaluation import PostconditionStanding
from baseltest.engine import RunResult

from .._steppers import CheckGroup, CriterionEvidence, ObservedExcerpt

_MAX_OBSERVED = 4
_MAX_EXPECTED = 3


def criterion_evidence(result: RunResult) -> tuple[CriterionEvidence, ...]:
    """Every criterion's standings, pooled into stepper evidence."""
    return tuple(
        CriterionEvidence(
            name=criterion_result.name,
            passed=criterion_result.tally.successes,
            trials=criterion_result.tally.trials,
            lower_bound=criterion_result.lower_bound,
            groups=_pool(criterion_result.standings),
        )
        for criterion_result in result.criterion_results
    )


def _pool(standings: Sequence[PostconditionStanding]) -> tuple[CheckGroup, ...]:
    """Standings pooled by ``(provenance, form, path)``, most failures first."""
    grouped: dict[tuple[str, str | None, str | None], list[PostconditionStanding]] = {}
    for standing in standings:
        key = (str(standing.provenance), standing.form, standing.path)
        grouped.setdefault(key, []).append(standing)
    groups = [
        CheckGroup(
            provenance=provenance,
            form=form,
            path=path,
            checks=len({s.postcondition for s in rows}),
            inputs=len({s.input_index for s in rows}),
            expected=_distinct_expected(rows),
            passed=sum(s.passed for s in rows),
            failed=sum(s.failed for s in rows),
            skipped=sum(s.skipped for s in rows),
            optional=all(s.optional for s in rows),
            observed=_pool_observed(rows),
        )
        for (provenance, form, path), rows in grouped.items()
    ]
    # Most failures first: a stepper reading top-down meets the largest
    # signal first, and a capped rendering keeps the part that matters.
    groups.sort(key=lambda group: (-group.failed, group.form or "", group.path or ""))
    return tuple(groups)


def _distinct_expected(rows: Sequence[PostconditionStanding]) -> tuple[str, ...]:
    """The distinct declared operands across pooled rows, capped."""
    seen: list[str] = []
    for row in rows:
        if row.expected is not None and row.expected not in seen:
            seen.append(row.expected)
    return tuple(seen[:_MAX_EXPECTED])


def _pool_observed(rows: Sequence[PostconditionStanding]) -> tuple[ObservedExcerpt, ...]:
    """Obtained-value exemplars pooled across rows, failing first, capped.

    Identical excerpts observed under different rows are one observation
    about the service, so their counts add; an excerpt seen both holding
    and not holding keeps both facts, because that difference is the
    signal.
    """
    totals: dict[tuple[str, bool], int] = {}
    for row in rows:
        for value in row.observed:
            totals[(value.excerpt, value.held)] = (
                totals.get((value.excerpt, value.held), 0) + value.count
            )
    ordered = sorted(totals.items(), key=lambda item: (item[0][1], -item[1], item[0][0]))
    return tuple(
        ObservedExcerpt(excerpt=excerpt, count=count, held=held)
        for (excerpt, held), count in ordered[:_MAX_OBSERVED]
    )
