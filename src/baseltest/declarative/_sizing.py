"""Risk-driven run sizing for the ``test`` verb: claims in, sample count out.

The operator declares how much genuine degradation they will tolerate and
how sure they want to be; the run's sample count is computed from those
claims against each empirical criterion's measured baseline. Claims come
from three places, in precedence order: a ``--tolerate`` flag, the
criterion's ``tolerate:`` contract key, and — on an interactive terminal —
a plain-language prompt. A non-interactive run with unclaimed empirical
criteria is refused before any invocation.

An explicit ``--samples`` stays available but never silent: the run is
priced in plain language (its acceptance floor and the drop it can
actually catch), and a weak design requires an explicit confirmation.
A tolerance at or above the proven baseline is pushed back on in the
other direction: the honest remedy is re-measuring, not asserting
improvement through the tolerance dial.
"""

import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from baseltest.baseline import StoredBaseline, resolve_baseline
from baseltest.engine import inputs_fingerprint
from baseltest.statistics import (
    check_feasibility,
    detectable_rate,
    power_at,
    required_samples_for_power,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)

from ._parser import FORMAT_IDENTIFIER, ContractDeclaration, CriterionDeclaration
from ._services import ServiceDefinition, resolved_provenance

DEFAULT_TARGET_POWER = 0.8

# An unclaimed explicit-samples design is called weak when the drop it can
# actually catch sits more than this far below the proven baseline.
_WEAK_DESIGN_MARGIN = 0.05

# A computed requirement above this is still honoured — the operator asked
# for it — but the output notes the honest cost and suggests relaxing.
LARGE_RUN_NOTE_LIMIT = 1000


class SizingRefusalError(Exception):
    """A run refused (or declined) before any service invocation; exit 2."""


@dataclass(frozen=True, slots=True)
class SizingClaim:
    """One empirical criterion's resolved sizing claim and its pricing."""

    criterion: str
    baseline_rate: float
    baseline_trials: int
    tolerated_rate: float
    confidence: float
    target_power: float
    required_n: int | None


@dataclass(frozen=True, slots=True)
class ResolvedSizing:
    """The ``test`` verb's resolved run size and everything it disclosed.

    ``samples`` is ``None`` on the legacy path (no empirical sizing
    engaged): the runner's own sizing story applies unchanged.
    """

    samples: int | None
    provenance: str | None = None
    claims: tuple[SizingClaim, ...] = ()
    governing: str | None = None
    approach: str | None = None


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _parse_rate(text: str, what: str) -> float:
    """A rate as either a proportion (``0.84``) or a percentage (``84``)."""
    try:
        value = float(text)
    except ValueError:
        raise SizingRefusalError(f"{what} must be a number, got {text!r}") from None
    if value >= 1.0:
        value = value / 100
    if math.isnan(value) or not 0.0 < value < 1.0:
        raise SizingRefusalError(
            f"{what} must be a rate between 0 and 1 (or a percentage), got {text}"
        )
    return value


def _effective_rate(successes: int, trials: int, confidence: float) -> float:
    """The baseline rate sizing runs against: the perfect-baseline guard.

    A perfect measure run overstates what is known; its own one-sided
    Wilson lower bound stands in as the proven rate, exactly as the
    threshold derivation treats it.
    """
    if successes == trials:
        return wilson_lower_bound(successes, trials, confidence)
    return successes / trials


@dataclass(frozen=True, slots=True)
class _EmpiricalCriterion:
    """One sizeable empirical criterion: its evidence and resolved claim."""

    name: str
    baseline_rate: float
    baseline_trials: int
    confidence: float
    tolerated_rate: float | None


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


def resolve_contract_baseline(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition],
    baseline_dir: Path,
) -> "StoredBaseline | None":
    """The baseline the empirical criteria would resolve, or ``None``.

    Mirrors the instantiation-time resolution (same identity keys), so the
    sizing conversation prices exactly the baseline the run will judge
    against.
    """
    definition = services.get(declaration.service)
    service_provenance = (
        resolved_provenance(definition.configuration) if definition is not None else {}
    )
    resolution = resolve_baseline(
        baseline_dir,
        declaration.contract,
        inputs_fingerprint(declaration.inputs),
        {
            "taskFormat": FORMAT_IDENTIFIER,
            "binding": declaration.service,
            **service_provenance,
        },
    )
    return resolution.baseline


def _sizeable_criteria(
    declaration: ContractDeclaration,
    baseline: StoredBaseline,
    tolerate_flags: dict[str, float],
    confidence_flag: float | None,
) -> list[_EmpiricalCriterion]:
    """The empirical criteria the baseline records, with claims resolved.

    Claim precedence per criterion: flag over contract key; an unclaimed
    criterion carries ``None`` and is the interactive mode's business.
    """
    sizeable = []
    for entry in declaration.criteria:
        if entry.threshold is not None:
            continue
        evidence = baseline.criteria.get(entry.name)
        if evidence is None or evidence.trials == 0:
            continue  # instantiation reports the skip; there is nothing to size
        confidence = _criterion_confidence(entry, declaration, confidence_flag)
        tolerated = tolerate_flags.get(entry.name)
        if tolerated is None:
            tolerated = entry.tolerate
        sizeable.append(
            _EmpiricalCriterion(
                name=entry.name,
                baseline_rate=_effective_rate(evidence.successes, evidence.trials, confidence),
                baseline_trials=evidence.trials,
                confidence=confidence,
                tolerated_rate=tolerated,
            )
        )
    return sizeable


def _criterion_confidence(
    entry: CriterionDeclaration,
    declaration: ContractDeclaration,
    confidence_flag: float | None,
) -> float:
    if confidence_flag is not None:
        return confidence_flag
    if entry.confidence is not None:
        return entry.confidence
    return declaration.confidence


def _over_reach_message(criterion: _EmpiricalCriterion) -> str:
    baseline = _percent(criterion.baseline_rate)
    asked = _percent(criterion.tolerated_rate or 0.0)
    suggestion = max(1, round(criterion.baseline_rate * 100) - 3)
    return (
        "Hold on — this asks for more than the evidence supports.\n"
        f"\n"
        f"Your measure run of {criterion.baseline_trials} samples proved criterion "
        f"{criterion.name} at {baseline}. That is the most reliable estimate you have "
        f"of how it truly performs. You have asked the test to confirm the real pass "
        f"rate is at least {asked} — at or above that measurement.\n"
        "\n"
        "Unless the system has genuinely improved since that run, this test is very "
        "likely to fail: it must prove the system is better than your own best "
        "measurement showed. Running more tests will not rescue it — a larger sample "
        f"pins the result more tightly around the true ~{baseline}, making a pass even "
        "less likely. Only a small, lucky sample could clear the bar.\n"
        "\n"
        "What you can do:\n"
        f"  - Set your lowest acceptable rate below {baseline} — the level you are "
        f'willing to defend as "still good enough" (e.g. --tolerate {suggestion})\n'
        "  - If you truly believe the system has improved, re-measure the baseline "
        "first (basel measure), then set your tolerance against the new proven rate."
    )


def _explanation(
    claim: SizingClaim, samples: int, *, governing: bool, several: bool, only_catch: bool = False
) -> str:
    """The plain-language explanation sentence, at the actual run size."""
    floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
    power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
    prefix = f"criterion {claim.criterion}: " if several else ""
    suffix = " (this criterion set the run size)" if governing and several else ""
    verb = "only catch" if only_catch else "catch"
    return (
        f"{prefix}If this test passes, you can be {_percent(claim.confidence)} confident "
        f"the true pass rate is at least {_percent(floor)}. This design will {verb} a "
        f"genuine drop to {_percent(claim.tolerated_rate)} about {_percent(power)} of "
        f"the time.{suffix}"
    )


def _sizing_table(claims: list[SizingClaim], samples: int, governing: str) -> list[str]:
    """The multi-criterion sizing block as one aligned table: a row per
    claim, priced at the governing run size, the governing row marked."""
    headers = (
        "criterion",
        "tolerates",
        "confidence",
        "drop caught",
        "a pass proves",
        "needs alone",
    )
    rows = []
    for claim in claims:
        floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
        power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
        rows.append(
            (
                claim.criterion,
                _percent(claim.tolerated_rate),
                _percent(claim.confidence),
                f"about {_percent(power)}",
                f"at least {_percent(floor)}",
                str(claim.required_n or 0),
            )
        )
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    lines = ["  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    for claim, row in zip(claims, rows, strict=True):
        cells = [row[0].ljust(widths[0])]
        cells.extend(row[i].rjust(widths[i]) for i in range(1, len(headers)))
        line = "  " + "  ".join(cells)
        if claim.criterion == governing:
            line += "  ← sets the run size"
        lines.append(line.rstrip())
    return lines


def _governing_samples(claims: list[SizingClaim], normative_minimum: int) -> tuple[int, str]:
    """The run size: the largest per-criterion requirement, floored by the
    normative criteria's feasibility minimum."""
    governing_claim = max(claims, key=lambda c: c.required_n or 0)
    samples = governing_claim.required_n or 0
    if normative_minimum > samples:
        return normative_minimum, governing_claim.criterion
    return samples, governing_claim.criterion


def _json_payload(
    claims: list[SizingClaim],
    samples: int,
    governing: str | None,
    explanations: list[str],
) -> dict[str, object]:
    """The machine-readable sizing block: per-criterion array, governing
    summary, and the flat single-criterion convenience fields."""
    criteria = []
    for claim in claims:
        floor = wilson_lower_bound_from_rate(claim.baseline_rate, samples, claim.confidence)
        power = power_at(samples, claim.baseline_rate, claim.tolerated_rate, claim.confidence)
        criteria.append(
            {
                "criterion": claim.criterion,
                "baseline_rate": claim.baseline_rate,
                "tolerated_rate": claim.tolerated_rate,
                "confidence": claim.confidence,
                "required_n": claim.required_n,
                "floor": floor,
                "power": power,
            }
        )
    lead = next((c for c in claims if c.criterion == governing), claims[0])
    lead_row = next(row for row in criteria if row["criterion"] == lead.criterion)
    return {
        "approach": "confidence-first (risk-driven)",
        "criteria": criteria,
        "governing": {"criterion": governing, "samples": samples},
        "baseline": lead.baseline_rate,
        "confidence": lead.confidence,
        "tolerableRate": lead.tolerated_rate,
        "targetPower": lead.target_power,
        "requiredSamples": lead.required_n,
        "acceptanceFloor": lead_row["floor"],
        "detectableDrop": detectable_rate(
            samples, lead.baseline_rate, lead.confidence, lead.target_power
        ),
        "explanation": "\n".join(explanations),
    }


@dataclass(frozen=True, slots=True)
class _Interaction:
    """How the sizing conversation talks: injectable for tests."""

    interactive: bool
    accept_weak_design: bool
    force: bool
    emit_json: bool
    ask: Callable[[str], str]
    say: Callable[[str], None]

    def confirm(self, question: str, *, default_yes: bool) -> bool:
        """A yes/no confirmation; non-interactive resolution is the caller's."""
        options = "[Y/n]" if default_yes else "[y/N]"
        answer = self.ask(f"{question} {options} ").strip().lower()
        if not answer:
            return default_yes
        return answer in ("y", "yes")


def _prompt_rate(interaction: _Interaction, criterion: _EmpiricalCriterion) -> float:
    """Ask for one criterion's lowest acceptable rate; re-ask until valid."""
    baseline_pct = round(criterion.baseline_rate * 100)
    default = max(1, baseline_pct - 3)
    interaction.say(
        f"\nThe proven baseline pass rate for criterion {criterion.name} is "
        f"{_percent(criterion.baseline_rate)} (from your measure run of "
        f"{criterion.baseline_trials} samples).\n"
        "\n"
        "What is the LOWEST real pass rate you are willing to accept?\n"
        "If the system has genuinely dropped below this, the test should fail.\n"
        f"(Enter a percentage between 1 and {baseline_pct - 1})  [default: {default}]"
    )
    while True:
        answer = interaction.ask("> ").strip()
        try:
            value = _parse_rate(answer, "the lowest acceptable rate") if answer else default / 100
        except SizingRefusalError as invalid:
            interaction.say(f"{invalid} — please try again.")
            continue
        if value >= criterion.baseline_rate:
            interaction.say(
                f"The lowest acceptable rate must be below the proven baseline of "
                f"{_percent(criterion.baseline_rate)} — please try again."
            )
            continue
        return value


def _prompt_confidence(interaction: _Interaction) -> float:
    """The one-time confidence question, in presets."""
    interaction.say(
        "\nHow sure do you want to be that a PASS is trustworthy?\n"
        "  [1] Standard - 95% sure  (recommended)\n"
        "  [2] High     - 99% sure  (more careful, needs more tests)\n"
        "  [3] Custom"
    )
    while True:
        answer = interaction.ask("> ").strip()
        if answer in ("", "1"):
            return 0.95
        if answer == "2":
            return 0.99
        if answer == "3":
            custom = interaction.ask("How sure, as a percentage (e.g. 97)? > ").strip()
            try:
                return _parse_rate(custom, "the confidence")
            except SizingRefusalError as invalid:
                interaction.say(f"{invalid} — please try again.")
                continue
        interaction.say("Please answer 1, 2, or 3.")


def _normative_minimum(declaration: ContractDeclaration) -> int:
    """The feasibility floor the normative criteria put under any run size."""
    minima = [
        check_feasibility(
            1, entry.threshold, _criterion_confidence(entry, declaration, None)
        ).minimum_samples
        for entry in declaration.criteria
        if entry.threshold is not None
    ]
    return max(minima, default=0)


def _priced_claim(criterion: _EmpiricalCriterion, target_power: float) -> SizingClaim:
    assert criterion.tolerated_rate is not None
    return SizingClaim(
        criterion=criterion.name,
        baseline_rate=criterion.baseline_rate,
        baseline_trials=criterion.baseline_trials,
        tolerated_rate=criterion.tolerated_rate,
        confidence=criterion.confidence,
        target_power=target_power,
        required_n=required_samples_for_power(
            criterion.baseline_rate,
            criterion.tolerated_rate,
            criterion.confidence,
            target_power,
        ),
    )


def _explicit_samples_mode(
    criteria: list[_EmpiricalCriterion],
    samples: int,
    target_power: float,
    interaction: _Interaction,
) -> ResolvedSizing:
    """Explicit-samples mode: run at the typed size, but price it first and
    require confirmation for a weak design."""
    several = len(criteria) > 1
    claims: list[SizingClaim] = []
    weak_lines: list[str] = []
    interaction.say(f"\nYou asked to run {samples} samples.\n\nWhat this means:")
    for criterion in criteria:
        if criterion.tolerated_rate is not None:
            claim = _priced_claim(criterion, target_power)
            required = claim.required_n or 0
            weak = samples < required
            interaction.say(
                _explanation(claim, samples, governing=False, several=several, only_catch=weak)
            )
            if weak:
                weak_lines.append(
                    f"To reliably catch a drop to {_percent(claim.tolerated_rate)} on "
                    f"criterion {claim.criterion}, you would need about {required} tests."
                )
        else:
            catchable = detectable_rate(
                samples, criterion.baseline_rate, criterion.confidence, target_power
            )
            claim = SizingClaim(
                criterion=criterion.name,
                baseline_rate=criterion.baseline_rate,
                baseline_trials=criterion.baseline_trials,
                tolerated_rate=catchable,
                confidence=criterion.confidence,
                target_power=target_power,
                required_n=None,
            )
            weak = catchable < criterion.baseline_rate - _WEAK_DESIGN_MARGIN
            interaction.say(
                _explanation(claim, samples, governing=False, several=several, only_catch=weak)
            )
            if weak:
                weak_lines.append(
                    f"A system that has quietly degraded to around "
                    f"{_percent(catchable)} on criterion {criterion.name} would still "
                    f"pass most of the time — that is far below your baseline of "
                    f"{_percent(criterion.baseline_rate)}."
                )
        claims.append(claim)
    if weak_lines and not (interaction.accept_weak_design or interaction.force):
        interaction.say("\nwarning: this is a weak test.")
        for line in weak_lines:
            interaction.say(f"  {line}")
        if not interaction.interactive:
            raise SizingRefusalError(
                "a weak test design needs an explicit go-ahead: re-run with "
                "--accept-weak-design to confirm it, raise --samples, or declare "
                "what the test must catch with --tolerate"
            )
        if not interaction.confirm("Continue anyway?", default_yes=False):
            raise SizingRefusalError("run declined — no samples were taken")
    if interaction.emit_json:
        interaction.say(json.dumps(_json_payload(claims, samples, None, []), indent=2))
    return ResolvedSizing(
        samples=samples,
        provenance="explicit",
        claims=tuple(claims),
        governing=None,
        approach="sample-size-first",
    )


def _risk_driven_mode(
    criteria: list[_EmpiricalCriterion],
    declaration: ContractDeclaration,
    target_power: float,
    interaction: _Interaction,
    *,
    prompted: bool,
) -> ResolvedSizing:
    """Fully-specified (or just-prompted) risk-driven sizing: compute the
    governing size, explain it, and — after prompting — confirm it."""
    claims = [_priced_claim(criterion, target_power) for criterion in criteria]
    samples, governing = _governing_samples(claims, _normative_minimum(declaration))
    several = len(claims) > 1
    explanations = [
        _explanation(claim, samples, governing=claim.criterion == governing, several=several)
        for claim in claims
    ]
    if interaction.emit_json:
        interaction.say(
            json.dumps(_json_payload(claims, samples, governing, explanations), indent=2)
        )
    else:
        qualifier = "tolerances" if several else "tolerance"
        interaction.say(
            f"\nThis test needs {samples} samples (computed from your declared {qualifier})."
        )
        if several:
            interaction.say("")
            for line in _sizing_table(claims, samples, governing):
                interaction.say(line)
        else:
            interaction.say(explanations[0])
        if samples > LARGE_RUN_NOTE_LIMIT:
            interaction.say(
                f"\nnote: a run of {samples} samples is the honest cost of the confidence "
                "and tolerance you asked for. To spend less, tolerate a larger drop "
                "(--tolerate) or accept a lower confidence (--confidence)."
            )
    if (
        prompted
        and not interaction.accept_weak_design
        and not interaction.confirm(f"\nRun {samples} samples now?", default_yes=True)
    ):
        raise SizingRefusalError("run declined — no samples were taken")
    return ResolvedSizing(
        samples=samples,
        provenance="risk-driven",
        claims=tuple(claims),
        governing=governing,
        approach="confidence-first (risk-driven)",
    )


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
    target_power = _parse_rate(power, "--power") if power is not None else DEFAULT_TARGET_POWER
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

    baseline = resolve_contract_baseline(declaration, services, baseline_dir)
    if baseline is None:
        if tolerate_flags:
            raise SizingRefusalError(
                "no matching baseline to size against — run `basel measure` first, "
                "then declare your tolerance"
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
    interaction.say("\nCalculating the number of tests needed...")
    return _risk_driven_mode(resolved, declaration, target_power, interaction, prompted=True)


def _needs_confidence_prompt(declaration: ContractDeclaration, criterion_name: str) -> bool:
    """Ask the confidence question only when nothing declared it."""
    entry = next(c for c in declaration.criteria if c.name == criterion_name)
    return entry.confidence is None and not declaration.confidence_declared


def _over_reach_mode(
    criteria: list[_EmpiricalCriterion],
    offender: _EmpiricalCriterion,
    samples: int | None,
    target_power: float,
    interaction: _Interaction,
) -> ResolvedSizing:
    """Addendum behaviour for a tolerance at or above the proven baseline:
    warn, never search for a required size, and demand a deliberate
    override (interactive confirmation, or ``--force`` in automation)."""
    interaction.say("\n" + _over_reach_message(offender))
    if not interaction.force:
        if not interaction.interactive:
            raise SizingRefusalError(
                f"the tolerance for criterion {offender.name} is at or above its "
                "proven baseline — re-run with --force to design the test anyway"
            )
        if not interaction.confirm("\nDesign the test anyway?", default_yes=False):
            raise SizingRefusalError("run declined — no samples were taken")
    if samples is None:
        raise SizingRefusalError(
            "no number of tests can be computed for a tolerance at or above the "
            "proven baseline (more tests only make a pass less likely) — choose "
            "the size yourself with --samples N"
        )
    # The over-reaching claim prices nothing; explain what the chosen size
    # actually buys instead, per criterion.
    priced = [
        c
        if c.tolerated_rate is None or c.tolerated_rate < c.baseline_rate
        else _EmpiricalCriterion(
            name=c.name,
            baseline_rate=c.baseline_rate,
            baseline_trials=c.baseline_trials,
            confidence=c.confidence,
            tolerated_rate=None,
        )
        for c in criteria
    ]
    return _explicit_samples_mode(priced, samples, target_power, interaction)
