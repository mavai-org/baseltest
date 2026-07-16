"""The check verb: every load-time join, zero samples."""

from collections.abc import Callable
from pathlib import Path

import pytest

from baseltest.declarative import binding, binding_factory
from baseltest.declarative._cli import main
from baseltest.declarative._registry import clear_registries


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


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
        calls: list[str] = []

        @binding_factory("fortune-teller")
        def fortune_teller(mood: str = "plain") -> Callable[[str], str]:
            def tell(name: str) -> str:
                calls.append(name)
                return f"{mood} {name}"

            return tell

        assert main(["check", str(write_files(tmp_path))]) == 0
        out = capsys.readouterr().out
        assert "ok: contract 'teller-stays-on-mood': 1 criteria, 1 inputs" in out
        assert "ok: service 'cheerful-teller': type 'fortune-teller', baseline" in out
        assert "ok: exploration grid: 1 entry constructed and joined" in out
        assert calls == []  # the compile step never invokes the service

    def test_bare_binding_contract_checks_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding("solo")
        def solo(name: str) -> str:
            return name

        contract = tmp_path / "contract.yaml"
        contract.write_text(CONTRACT.replace("service: cheerful-teller", "service: solo"))
        assert main(["check", str(contract)]) == 0
        assert "binding resolved" in capsys.readouterr().out

    def test_configuration_misfit_fails_with_the_join_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding_factory("fortune-teller")
        def fortune_teller(tone: str = "plain") -> Callable[[str], str]:
            return lambda name: name

        assert main(["check", str(write_files(tmp_path))]) == 2
        assert "unknown key `mood:`" in capsys.readouterr().err

    def test_input_arity_misfit_in_a_grid_point_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        @binding_factory("fortune-teller")
        def fortune_teller(mood: str = "plain") -> Callable[[str, int], str]:
            def tell(name: str, sincerity: int) -> str:
                return f"{mood} {name} {sincerity}"

            return tell

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
