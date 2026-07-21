"""The declarative + artefact closed sets carry their exact contract strings.

`Objective`, `Termination`, `JudgementState` and `LatencyBasis` are emitted
verbatim into the interchange artefacts; `Intent`, `Form` and `Phase` are the
contract-format vocabulary the parser accepts. A rename of any value here is a
breaking format/wire change, not a local refactor — so the values are pinned.
The four StrEnum sets that reach an artefact must also stay byte-identical to
the bare strings they replaced, so the writers that stringify them are unchanged.
"""

import json

from baseltest.baseline import JudgementState
from baseltest.declarative._parser import Form
from baseltest.declarative._steppers import Phase
from baseltest.engine import Intent, LatencyBasis
from baseltest.optimization import Objective, Termination


def test_objective_values() -> None:
    assert {o.value for o in Objective} == {"maximize", "minimize"}


def test_termination_values() -> None:
    assert {t.value for t in Termination} == {
        "max-iterations",
        "no-improvement-window",
        "stepper-stopped",
        "defect",
    }


def test_judgement_state_values() -> None:
    assert {s.value for s in JudgementState} == {"met", "failed"}


def test_latency_basis_values() -> None:
    assert {b.value for b in LatencyBasis} == {"passing-samples"}


def test_intent_values() -> None:
    assert {i.value for i in Intent} == {"verification", "smoke"}


def test_form_values() -> None:
    assert {f.value for f in Form} == {
        "equals",
        "one-of",
        "contains",
        "matches",
        "parses",
        "satisfies",
    }


def test_phase_values() -> None:
    assert {p.value for p in Phase} == {"start", "grid", "confirm", "done"}


def test_artefact_sets_are_byte_identical_to_their_strings() -> None:
    # The four that reach an artefact serialise to their wire string unchanged.
    emitted = (
        Objective.MAXIMIZE,
        Termination.DEFECT,
        JudgementState.MET,
        LatencyBasis.PASSING_SAMPLES,
    )
    for member in emitted:
        assert member == member.value
        assert json.dumps(member) == json.dumps(member.value)
