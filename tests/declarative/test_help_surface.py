"""``--help`` states every verb and every option a caller may pass.

A flag reachable from the command line and absent from its help screen is
reachable only by whoever already knew about it — the reader it exists for
concludes it does not exist. These lock the help surface to the parser
rather than to a copy of it, so a flag added later is documented or the
suite says so.
"""

import argparse

import pytest

from baseltest.declarative._cli import _build_parser

VERBS = ("test", "measure", "explore", "optimize", "report", "check")
# The verbs that write artefacts render them in the same breath.
RENDERING_VERBS = ("test", "measure", "explore", "optimize")


def verb_parsers() -> dict[str, argparse.ArgumentParser]:
    """The subparser registered against each verb."""
    actions = [
        action
        for action in _build_parser()._actions  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    ]
    assert len(actions) == 1, "one verb group"
    return dict(actions[0].choices)


def test_every_verb_is_registered() -> None:
    assert sorted(verb_parsers()) == sorted(VERBS)


@pytest.mark.parametrize("verb", VERBS)
def test_a_verb_states_what_it_does_on_its_own_screen(verb: str) -> None:
    """`basel <verb> --help` opens with the verb's description, not a bare usage line."""
    assert verb_parsers()[verb].description


@pytest.mark.parametrize("verb", VERBS)
def test_a_verb_documents_every_option_it_accepts(verb: str) -> None:
    """No option is suppressed: what the parser accepts, the help states."""
    undocumented = [
        option
        for action in verb_parsers()[verb]._actions  # noqa: SLF001
        for option in action.option_strings
        if action.help is argparse.SUPPRESS or not action.help
    ]
    assert not undocumented


@pytest.mark.parametrize("verb", RENDERING_VERBS)
def test_a_verb_that_writes_artefacts_documents_the_report_flag(verb: str) -> None:
    options = {
        option
        for action in verb_parsers()[verb]._actions  # noqa: SLF001
        for option in action.option_strings
    }
    assert "--html-report" in options


def test_the_top_level_screen_points_at_the_per_verb_screens() -> None:
    """The verbs' flags live one screen down, and nothing else says so."""
    assert "--help" in (_build_parser().epilog or "")
