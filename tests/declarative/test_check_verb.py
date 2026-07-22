"""The check verb: every load-time join, zero samples."""

from pathlib import Path

import pytest

from baseltest.declarative._cli import main

SERVICES = """
format: mavai-services/1
services:
  cheerful-teller:
    type: fortune-teller
    configuration:
      mood: cheerful
    explorations:
      - mood: gloomy
"""

CONTRACT = """
format: mavai-contract/1
contract: teller-stays-on-mood
service: cheerful-teller
criteria:
  - threshold: 0.5
    contains: "cheerful"
inputs: ["Alice"]
"""


def write_files(tmp_path: Path, services: str = SERVICES, contract: str = CONTRACT) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


class TestCheckVerb:
    def test_valid_files_pass_with_facts_and_zero_invocations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = tmp_path / "tell-invoked"
        (tmp_path / "mavai-bindings.py").write_text(
            "from collections.abc import Callable\n"
            "from pathlib import Path\n"
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding_factory('fortune-teller')\n"
            "def fortune_teller(mood: str = 'plain') -> Callable[[str], str]:\n"
            "    def tell(name: str) -> str:\n"
            f"        Path({str(marker)!r}).touch()\n"
            "        return f'{mood} {name}'\n"
            "    return tell\n",
            encoding="utf-8",
        )

        assert main(["check", str(write_files(tmp_path))]) == 0
        out = capsys.readouterr().out
        assert "ok: contract 'teller-stays-on-mood': 1 criteria, 1 inputs" in out
        assert "ok: service 'cheerful-teller': type 'fortune-teller', baseline" in out
        assert "ok: exploration grid: 1 entry constructed and joined" in out
        assert not marker.exists()  # the compile step never invokes the service

    def test_bare_binding_contract_checks_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "mavai-bindings.py").write_text(
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding('solo')\n"
            "def solo(name: str) -> str:\n"
            "    return name\n",
            encoding="utf-8",
        )

        contract = tmp_path / "contract.yaml"
        contract.write_text(CONTRACT.replace("service: cheerful-teller", "service: solo"))
        assert main(["check", str(contract)]) == 0
        assert "binding resolved" in capsys.readouterr().out

    def test_a_custom_view_path_is_validated_with_zero_samples(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "mavai-bindings.py").write_text(
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding('solo')\n"
            "def solo(name: str) -> str:\n"
            "    return name\n"
            "@bindings.transform('judge')\n"
            "def judge(raw: str) -> dict[str, bool]:\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )

        contract = tmp_path / "contract.yaml"
        contract.write_text(
            """
format: mavai-contract/1
contract: t
service: solo
transforms:
  judged: judge
criteria:
  - threshold: 0.5
    postconditions:
      - in: judged
        path: "$[["
        equals: "1"
inputs: ["a"]
"""
        )
        assert main(["check", str(contract)]) == 2
        assert "JSONPath" in capsys.readouterr().err

    def test_configuration_misfit_fails_with_the_join_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "mavai-bindings.py").write_text(
            "from collections.abc import Callable\n"
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding_factory('fortune-teller')\n"
            "def fortune_teller(tone: str = 'plain') -> Callable[[str], str]:\n"
            "    return lambda name: name\n",
            encoding="utf-8",
        )

        assert main(["check", str(write_files(tmp_path))]) == 2
        assert "unknown key `mood:`" in capsys.readouterr().err

    def test_input_arity_misfit_in_a_grid_point_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "mavai-bindings.py").write_text(
            "from collections.abc import Callable\n"
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding_factory('fortune-teller')\n"
            "def fortune_teller(mood: str = 'plain') -> Callable[[str, int], str]:\n"
            "    def tell(name: str, sincerity: int) -> str:\n"
            "        return f'{mood} {name} {sincerity}'\n"
            "    return tell\n",
            encoding="utf-8",
        )

        assert main(["check", str(write_files(tmp_path))]) == 2
        message = capsys.readouterr().err
        assert "input 1" in message
        assert "1 value" in message

    def test_unresolvable_service_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        contract = tmp_path / "contract.yaml"
        contract.write_text(CONTRACT)
        assert main(["check", str(contract)]) == 2
        assert "cheerful-teller" in capsys.readouterr().err
