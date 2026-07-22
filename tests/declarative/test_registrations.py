"""The mavai-bindings.py convention: discovered, imported once, refused helpfully."""

from pathlib import Path

import pytest

from baseltest.declarative import Bindings, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.statistics.verdict import Verdict

CONTRACT = """
format: mavai-contract/1
contract: conventioned
service: convention-service
inputs: ["a"]
criteria:
  - threshold: 0.5
    contains: "ok"
"""

BINDINGS = """
from baseltest.declarative import Bindings

bindings = Bindings()

@bindings.binding("convention-service")
def invoke(value: str) -> str:
    return f"ok {value}"
"""


def test_bindings_file_beside_contract_is_discovered(tmp_path: Path) -> None:
    (tmp_path / "mavai-bindings.py").write_text(BINDINGS, encoding="utf-8")
    contract = tmp_path / "contract.yaml"
    contract.write_text(CONTRACT, encoding="utf-8")
    result = run(contract, emit=False)
    assert result.composite is Verdict.PASS


def test_broken_bindings_file_is_a_constructive_refusal(tmp_path: Path) -> None:
    (tmp_path / "mavai-bindings.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")
    contract = tmp_path / "contract.yaml"
    contract.write_text(CONTRACT, encoding="utf-8")
    with pytest.raises(ContractConfigurationError, match="mavai-bindings.py"):
        run(contract, emit=False)


def test_absent_bindings_file_leaves_in_process_registration_working(tmp_path: Path) -> None:
    bindings = Bindings()

    @bindings.binding("convention-service")
    def invoke(value: str) -> str:
        return f"ok {value}"

    contract = tmp_path / "contract.yaml"
    contract.write_text(CONTRACT, encoding="utf-8")
    assert run(contract, bindings=bindings, emit=False).composite is Verdict.PASS
