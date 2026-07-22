"""The interactive sizing conversation: the channel and the questions.

``_Interaction`` is the injectable I/O channel (so tests can drive the
conversation without a terminal); the prompts ask for a criterion's lowest
acceptable rate and the one-time confidence, re-asking until valid.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .._parser import ContractDeclaration
from ._model import SizingRefusalError, _EmpiricalCriterion
from ._rates import _parse_rate, _percent


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
        "  [2] High     - 99% sure  (more careful, needs more samples)\n"
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


def _needs_confidence_prompt(declaration: ContractDeclaration, criterion_name: str) -> bool:
    """Ask the confidence question only when nothing declared it."""
    entry = next(c for c in declaration.criteria if c.name == criterion_name)
    return entry.confidence is None and not declaration.confidence_declared
