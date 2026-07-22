"""The sizing flags: refusing contradictory sources, resolving ``--tolerate``.

One sizing source per invocation — an explicit ``--samples`` cannot be
combined with the risk-driven claim flags — and the ``--tolerate`` values
resolved to per-criterion rates (bare or ``CRITERION=RATE``).
"""

from ._model import SizingRefusalError
from ._rates import _parse_rate


def _refuse_contradictory_sizing_flags(
    samples: int | None, tolerate: list[str] | None, power: str | None, force: bool
) -> None:
    """One sizing source per invocation: an explicit ``--samples`` cannot be
    combined with the risk-driven claim flags.

    ``--force`` lifts the conflict: the over-reach fallthrough demands an
    explicit ``--samples`` alongside the tolerance, because no size can be
    computed in that regime. Contract-file ``tolerate:`` keys are not a
    conflict — an explicit ``--samples`` against declared claims runs at
    the chosen n, priced in plain language.
    """
    if samples is None or force:
        return
    if tolerate:
        raise SizingRefusalError(
            "--samples and --tolerate are contradictory sizing instructions "
            "(--tolerate computes the sample count) — drop one of them, or "
            "declare `tolerate:` in the contract file to price an explicit "
            "--samples run"
        )
    if power is not None:
        raise SizingRefusalError(
            "--samples and --power are contradictory sizing instructions "
            "(--power shapes a computed sample count) — drop one of them"
        )


def _parse_tolerate_flags(
    entries: list[str] | None, empirical_names: list[str]
) -> dict[str, float]:
    """The ``--tolerate`` flag values, resolved to per-criterion rates."""
    if not entries:
        return {}
    named: dict[str, float] = {}
    bare: list[float] = []
    for entry in entries:
        name, separator, rate_text = entry.partition("=")
        if separator:
            if name not in empirical_names:
                known = ", ".join(empirical_names) or "none"
                raise SizingRefusalError(
                    f"--tolerate names unknown criterion {name!r} "
                    f"(empirical criteria in this contract: {known})"
                )
            if name in named:
                raise SizingRefusalError(f"--tolerate names criterion {name!r} more than once")
            named[name] = _parse_rate(rate_text, f"--tolerate for criterion {name}")
        else:
            bare.append(_parse_rate(entry, "--tolerate"))
    if bare and named:
        raise SizingRefusalError(
            "--tolerate mixes the bare form with the CRITERION=RATE form — "
            "use one style per invocation"
        )
    if len(bare) > 1:
        raise SizingRefusalError(
            "a bare --tolerate may be given once; name criteria to give several"
        )
    if bare:
        if len(empirical_names) != 1:
            names = ", ".join(f"--tolerate {name}=RATE" for name in empirical_names)
            raise SizingRefusalError(
                "a bare --tolerate is ambiguous against several empirical criteria — "
                f"name each one: {names}"
            )
        return {empirical_names[0]: bare[0]}
    return named
