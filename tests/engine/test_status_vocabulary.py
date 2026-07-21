"""The status enums carry the family's exact wire strings.

These three closed sets are emitted verbatim into the interchange artefacts
and the verdict XML, so their values are a wire contract: a rename here is a
breaking artefact change, not a local refactor. As StrEnum members they must
also remain byte-identical to the bare strings they replaced — equal to the
string and serialising to it — so writers that stringify them stay unchanged.
"""

import json

from baseltest.contract import Outcome
from baseltest.engine import BarAttainment, BoundStatus


def test_outcome_wire_values() -> None:
    assert {o.value for o in Outcome} == {"passed", "failed", "skipped"}


def test_bound_status_wire_values() -> None:
    assert {s.value for s in BoundStatus} == {"pass", "fail", "infeasible"}


def test_bar_attainment_wire_values() -> None:
    assert {b.value for b in BarAttainment} == {"met", "not met", "unsupportable"}


def test_members_are_byte_identical_to_their_strings() -> None:
    # str-equality and str-serialisation are what keep every emitter unchanged.
    for member in (Outcome.FAILED, BoundStatus.INFEASIBLE, BarAttainment.NOT_MET):
        assert member == member.value
        assert str(member) == member.value
        assert json.dumps(member) == json.dumps(member.value)
