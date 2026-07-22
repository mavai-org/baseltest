"""PR-12a acceptance: two registries with the same binding name never cross-talk.

Two independent :class:`Registry` instances each bind the same service name to
a different implementation. Run in one process, over the same contract, each
resolves against its own registrations — no global reset, no shared singleton.
"""

from pathlib import Path

from baseltest.declarative import Registry, run
from baseltest.engine import Verdict

CONTRACT = """
format: mavai-contract/1
contract: isolation
service: svc
criteria:
  - threshold: 0.5
    contains: "MARKER"
inputs: ["x"]
"""


def _write(tmp_path: Path, marker: str) -> Path:
    path = tmp_path / f"contract-{marker}.yaml"
    path.write_text(CONTRACT.replace("MARKER", marker), encoding="utf-8")
    return path


def test_two_registries_same_binding_name_do_not_cross_talk(tmp_path: Path) -> None:
    r1 = Registry()
    r2 = Registry()

    @r1.binding("svc")
    def invoke_a(value: str) -> str:
        return "A for you"

    @r2.binding("svc")
    def invoke_b(value: str) -> str:
        return "B for you"

    contract_a = _write(tmp_path, "A")
    contract_b = _write(tmp_path, "B")

    # Each registry sees its own binding: r1's "svc" answers "A", r2's "B".
    assert run(contract_a, registry=r1, emit=False).composite is Verdict.PASS
    assert run(contract_b, registry=r2, emit=False).composite is Verdict.PASS

    # And no bleed-through: r2's "svc" (answers "B") fails the "A" contract,
    # and r1's (answers "A") fails the "B" contract — proving the second
    # registration never overwrote or leaked into the first.
    assert run(contract_a, registry=r2, emit=False).composite is Verdict.FAIL
    assert run(contract_b, registry=r1, emit=False).composite is Verdict.FAIL
