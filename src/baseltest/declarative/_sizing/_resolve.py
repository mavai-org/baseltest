"""The ``test``-verb sizing resolver: claims in, sample count out.

Dispatches the resolved empirical criteria to exactly one mode after the
flag and baseline gates: over-reach, explicit-samples, fully-specified
risk-driven, or the interactive prompt loop. Engages only when the contract
carries empirical criteria a resolved baseline can price; otherwise the
legacy sizing story applies untouched (``samples=None`` signals passthrough).
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from baseltest.statistics import DEFAULT_POWER

from .._parser import ContractDeclaration
from .._services import ServiceDefinition
from ._criteria import _sizeable_criteria, resolve_contract_baseline
from ._flags import _parse_tolerate_flags, _refuse_contradictory_sizing_flags
from ._model import ResolvedSizing, SizingRefusalError, _EmpiricalCriterion
from ._modes import _explicit_samples_mode, _over_reach_mode, _risk_driven_mode
from ._prompts import (
    _Interaction,
    _needs_confidence_prompt,
    _prompt_confidence,
    _prompt_rate,
)
from ._rates import _parse_rate

if TYPE_CHECKING:
    from .._registry import Registry


def resolve_test_sizing(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition],
    *,
    baseline_dir: Path,
    samples: int | None,
    tolerate: list[str] | None,
    confidence: str | None,
    power: str | None,
    accept_weak_design: bool,
    emit_json: bool,
    force: bool,
    registry: "Registry",
    ask: Callable[[str], str] | None = None,
    say: Callable[[str], None] | None = None,
) -> ResolvedSizing:
    """Resolve the ``test`` verb's run size from the operator's stated risk.

    Engages only when the contract carries empirical criteria a resolved
    baseline can price; otherwise the legacy sizing story applies
    untouched (``samples=None`` in the result signals passthrough).

    Raises:
        SizingRefusalError: A refusal or declined confirmation, before any
            invocation — the CLI maps it to exit code 2. In particular,
            contradictory sizing instructions: an explicit ``--samples``
            together with ``--tolerate`` or ``--power`` (without the
            over-reach fallthrough's ``--force``).
    """
    _refuse_contradictory_sizing_flags(samples, tolerate, power, force)
    interaction = _Interaction(
        interactive=sys.stdin.isatty() and not emit_json,
        accept_weak_design=accept_weak_design,
        force=force,
        emit_json=emit_json,
        # Resolved at call time so a test harness's stand-ins apply.
        ask=ask if ask is not None else input,
        say=say if say is not None else print,
    )
    target_power = _parse_rate(power, "--power") if power is not None else DEFAULT_POWER
    confidence_flag = _parse_rate(confidence, "--confidence") if confidence is not None else None

    empirical_names = [c.name for c in declaration.criteria if c.threshold is None]
    if not empirical_names:
        if tolerate:
            raise SizingRefusalError(
                "--tolerate sizes the test against a measured baseline, and every "
                "criterion in this contract declares its own threshold — there is "
                "no baseline claim to protect"
            )
        return ResolvedSizing(samples=samples, approach="threshold-first")
    tolerate_flags = _parse_tolerate_flags(tolerate, empirical_names)

    resolution = resolve_contract_baseline(declaration, services, baseline_dir, registry)
    baseline = resolution.baseline
    if baseline is None:
        if tolerate_flags:
            detail = f" ({resolution.reason})" if resolution.reason else ""
            raise SizingRefusalError(
                f"no matching baseline to size against{detail} — run `basel measure` "
                "first, then declare your tolerance"
            )
        return ResolvedSizing(samples=samples)

    criteria = _sizeable_criteria(declaration, baseline, tolerate_flags, confidence_flag)
    if not criteria:
        return ResolvedSizing(samples=samples)

    over_reaching = [
        c for c in criteria if c.tolerated_rate is not None and c.tolerated_rate >= c.baseline_rate
    ]
    if over_reaching:
        return _over_reach_mode(criteria, over_reaching[0], samples, target_power, interaction)

    if samples is not None:
        return _explicit_samples_mode(criteria, samples, target_power, interaction)

    unclaimed = [c for c in criteria if c.tolerated_rate is None]
    if not unclaimed:
        return _risk_driven_mode(criteria, declaration, target_power, interaction, prompted=False)

    if not interaction.interactive:
        flags = " ".join(f"--tolerate {c.name}=RATE" for c in unclaimed)
        raise SizingRefusalError(
            "cannot size the run: no tolerance is declared for "
            f"{', '.join(c.name for c in unclaimed)} and there is no terminal to ask "
            f"on. Declare the claim in the contract file (`tolerate:`) or pass "
            f"flags, e.g. `basel test <contract> {flags} --confidence 95`, or size "
            "it yourself with --samples N"
        )

    session_confidence: float | None = confidence_flag
    resolved: list[_EmpiricalCriterion] = []
    for criterion in criteria:
        if criterion.tolerated_rate is not None:
            resolved.append(criterion)
            continue
        if session_confidence is None and _needs_confidence_prompt(declaration, criterion.name):
            session_confidence = _prompt_confidence(interaction)
        effective = (
            criterion
            if session_confidence is None
            else _EmpiricalCriterion(
                name=criterion.name,
                baseline_rate=criterion.baseline_rate,
                baseline_trials=criterion.baseline_trials,
                confidence=session_confidence,
                tolerated_rate=None,
            )
        )
        rate = _prompt_rate(interaction, effective)
        resolved.append(
            _EmpiricalCriterion(
                name=effective.name,
                baseline_rate=effective.baseline_rate,
                baseline_trials=effective.baseline_trials,
                confidence=effective.confidence,
                tolerated_rate=rate,
            )
        )
    over = [
        c for c in resolved if c.tolerated_rate is not None and c.tolerated_rate >= c.baseline_rate
    ]
    if over:  # unreachable via prompt validation, reachable via keys+prompt mixes
        return _over_reach_mode(resolved, over[0], samples, target_power, interaction)
    interaction.say("\nCalculating the number of samples needed...")
    return _risk_driven_mode(resolved, declaration, target_power, interaction, prompted=True)
