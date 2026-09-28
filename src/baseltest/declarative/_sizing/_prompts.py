"""The interactive sizing conversation: the channel and the questions.

``_Interaction`` is the injectable I/O channel (so tests can drive the
conversation without a terminal); the prompts ask for a criterion's design
alternative rate (the rate to catch) and the one-time confidence, re-asking
until valid.
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
    """Ask for one criterion's design alternative rate; re-ask until valid."""
    baseline_pct = round(criterion.baseline_rate * 100)
    default = max(1, baseline_pct - 3)
    interaction.say(
        f"\nThe baseline pass rate for criterion {criterion.name} is "
        f"{_percent(criterion.baseline_rate)} ({criterion.baseline_successes} of "
        f"{criterion.baseline_trials} samples in your measure run).\n"
        "\n"
        "The test flags any drop from that baseline it can see. Which degraded pass\n"
        "rate must it catch reliably? If the system has genuinely dropped to this\n"
        "rate, the test should fail almost every time.\n"
        f"(Enter a percentage between 1 and {baseline_pct - 1})  [default: {default}]"
    )
    while True:
        answer = interaction.ask("> ").strip()
        try:
            value = _parse_rate(answer, "the rate to catch") if answer else default / 100
        except SizingRefusalError as invalid:
            interaction.say(f"{invalid} — please try again.")
            continue
        if value >= criterion.baseline_rate:
            interaction.say(
                f"The rate to catch must be below the baseline rate of "
                f"{_percent(criterion.baseline_rate)} — please try again."
            )
            continue
        return value


def _prompt_confidence(interaction: _Interaction) -> float:
    """The one-time confidence question, in presets."""
    interaction.say(
        "\nHow rarely may the test raise a false alarm on an unchanged service?\n"
        "  [1] Standard - 95% confidence, 1 run in 20  (recommended)\n"
        "  [2] High     - 99% confidence, 1 run in 100 (needs more samples)\n"
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
