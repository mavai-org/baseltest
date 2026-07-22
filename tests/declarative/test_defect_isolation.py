"""Transform defect isolation: a defect stops its configuration, not the run.

A non-``TransformError`` exception escaping a view transformation is a
*defect* — a bug in the testing machinery, never a countable outcome and
never a sample. It must stop *its* configuration with an actionable
diagnosis, but it must not forfeit every other configuration's paid spend.
These tests pin that containment, the diagnosis message's content, and the
stock ``json`` view's honest reporting of CPython's int-string guard.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import Bindings, explore, optimize
from baseltest.declarative._cli import main
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL

SERVICES = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.2
    explorations:
      - temperature: 0.0
      - temperature: 0.7
      - model: other-model
        temperature: 0.7
"""

CONTRACT = """
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs: ["Where is my order?", "Do you ship abroad?"]
transforms:
  judged: judge
criteria:
  - name: verdict-ok
    threshold: 0.5
    postconditions:
      - in: judged
        path: "$.ok"
        equals: "true"
"""


@pytest.fixture()
def poison_one_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stubbed endpoint that returns a degenerate draw for one configuration.

    Every configuration but ``other-model`` gets valid JSON; ``other-model``
    gets a non-JSON body that the custom transform below chokes on with a
    plain ``ValueError`` — the field's failure mode reproduced at the grid
    level.
    """

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request: Any) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        content = "POISON" if payload["model"] == "other-model" else '{"ok": true}'
        reply = {"choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def register_choking_judge(bindings: Bindings) -> None:
    """A custom transform that raises a non-TransformError on a degenerate draw.

    It catches nothing: a real custom transform cannot anticipate the
    exception it did not foresee. On a poison body ``json.loads`` never
    runs — the plain ``ValueError`` here stands in for that unforeseen
    escape.
    """

    @bindings.transform("judge")
    def judge(raw: str) -> dict[str, object]:
        if "POISON" in raw:
            raise ValueError("degenerate draw: unusable response")
        return json.loads(raw)  # type: ignore[no-any-return]


# The same choking judge, expressed as a ``mavai-bindings.py`` module body for
# the CLI-driven runs that self-discover their registrations beside the contract.
JUDGE_BINDINGS = (
    "import json\n"
    "from baseltest.declarative import Bindings\n"
    "bindings = Bindings()\n"
    "@bindings.transform('judge')\n"
    "def judge(raw: str) -> dict[str, object]:\n"
    "    if 'POISON' in raw:\n"
    "        raise ValueError('degenerate draw: unusable response')\n"
    "    return json.loads(raw)\n"
)


def write_files(tmp_path: Path, contract: str = CONTRACT, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


class TestExploreContainsDefects:
    def test_one_configurations_defect_does_not_abort_the_others(
        self, tmp_path: Path, poison_one_configuration: None
    ) -> None:
        # Field regression (hibu-bkb-kg spec 007): one defect discarded every
        # configuration's paid spend.
        bindings = Bindings()
        register_choking_judge(bindings)
        exploration = explore(
            write_files(tmp_path),
            samples_per_config=3,
            explorations_dir=tmp_path / "x",
            emit=False,
            bindings=bindings,
        )
        assert len(exploration.completed) == 3
        assert len(exploration.aborted) == 1
        artefacts = sorted(p.name for p in (tmp_path / "x" / "support-agent-tuning").glob("*.yaml"))
        assert len(artefacts) == 3
        aborted = exploration.aborted[0]
        assert aborted.factors["model"] == "other-model"
        assert "model-other-model" not in " ".join(artefacts)

    def test_cli_reports_the_partial_run_with_a_non_zero_exit(
        self, tmp_path: Path, poison_one_configuration: None, capsys: Any
    ) -> None:
        contract = write_files(tmp_path)
        (tmp_path / "mavai-bindings.py").write_text(JUDGE_BINDINGS, encoding="utf-8")
        code = main(
            ["explore", str(contract), "--explorations-dir", str(tmp_path / "x")]
        )
        assert code == 1
        captured = capsys.readouterr()
        assert "explored 3 configuration" in captured.out
        assert "aborted with a defect" in captured.out
        assert "other-model" in captured.err


class TestDefectDiagnosisErrorMessage:
    def test_message_names_transform_criterion_postcondition_exception_and_input(
        self, tmp_path: Path, poison_one_configuration: None
    ) -> None:
        bindings = Bindings()
        register_choking_judge(bindings)
        exploration = explore(
            write_files(tmp_path),
            samples_per_config=2,
            explorations_dir=tmp_path / "x",
            emit=False,
            bindings=bindings,
        )
        diagnosis = exploration.aborted[0].diagnosis
        assert "judged" in diagnosis
        assert "verdict-ok" in diagnosis
        assert "at $.ok" in diagnosis
        assert "ValueError" in diagnosis
        assert "degenerate draw: unusable response" in diagnosis
        assert "input 0" in diagnosis
        assert "Where is my order?" in diagnosis
        assert "raising TransformError" in diagnosis
        assert "treated as a defect" in diagnosis


class TestSingleConfigCliBackstop:
    def test_measure_defect_surfaces_the_diagnosis_not_a_traceback(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        # No siblings to save here — the diagnosis is the whole point.
        (tmp_path / "mavai-bindings.py").write_text(
            "import json\n"
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "@bindings.binding('bulk-svc')\n"
            "def invoke(value: str) -> str:\n"
            "    return 'POISON'\n"
            "@bindings.transform('judge')\n"
            "def judge(raw: str) -> dict[str, object]:\n"
            "    if 'POISON' in raw:\n"
            "        raise ValueError('degenerate draw: unusable response')\n"
            "    return json.loads(raw)\n",
            encoding="utf-8",
        )
        contract = CONTRACT.replace("service: support-agent", "service: bulk-svc")
        path = tmp_path / "contract.yaml"
        path.write_text(contract, encoding="utf-8")
        code = main(["measure", str(path), "--samples", "4", "--baseline-dir", str(tmp_path / "b")])
        assert code == 1
        err = capsys.readouterr().err
        assert "a defect stopped the run" in err
        assert "judged" in err
        assert "ValueError" in err
        assert "raising TransformError" in err


class TestOptimizeContainsDefects:
    OPTIMIZE_SERVICES = """
format: mavai-services/1
services:
  bulk-svc:
    type: language-model
    configuration:
      system-prompt: "s"
      model: small-model
      temperature: 0.0
    optimizations:
      - id: warm-up
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.2, stop: 0.6}
        max-iterations: 3
"""

    def _write(self, tmp_path: Path) -> Path:
        (tmp_path / "mavai-services.yaml").write_text(self.OPTIMIZE_SERVICES, encoding="utf-8")
        path = tmp_path / "contract.yaml"
        path.write_text(CONTRACT.replace("service: support-agent", "service: bulk-svc"), "utf-8")
        return path

    @pytest.fixture()
    def poison_after_first_iteration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid JSON at temperature 0.0, a poison body once the sweep moves on."""

        class FakeResponse(io.BytesIO):
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                self.close()

        def fake_urlopen(request: Any) -> FakeResponse:
            payload = json.loads(request.data.decode("utf-8"))
            content = '{"ok": true}' if payload["temperature"] == 0.0 else "POISON"
            reply = {"choices": [{"message": {"content": content}}]}
            return FakeResponse(json.dumps(reply).encode("utf-8"))

        monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
        monkeypatch.setenv(ENV_MODEL, "env-default-model")
        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    def test_defected_iteration_stops_the_search_and_keeps_the_history(
        self, tmp_path: Path, poison_after_first_iteration: None
    ) -> None:
        bindings = Bindings()
        register_choking_judge(bindings)
        outcomes = optimize(
            self._write(tmp_path),
            samples_per_iteration=2,
            optimizations_dir=tmp_path / "o",
            emit=False,
            bindings=bindings,
        )
        outcome = outcomes[0]
        # Iteration 0 (temperature 0.0) scored; iteration 1 drew the poison.
        assert outcome.defect is not None
        assert outcome.record is not None
        assert outcome.record.termination == "defect"
        assert len(outcome.record.iterations) == 1
        assert outcome.path is not None and outcome.path.is_file()

    def test_a_first_iteration_defect_yields_no_artefact_but_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every draw is poison, so iteration 0 itself defects: no scored
        # history to persist.
        class FakeResponse(io.BytesIO):
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                self.close()

        def fake_urlopen(request: Any) -> FakeResponse:
            reply = {"choices": [{"message": {"content": "POISON"}}]}
            return FakeResponse(json.dumps(reply).encode("utf-8"))

        monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
        monkeypatch.setenv(ENV_MODEL, "env-default-model")
        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        bindings = Bindings()
        register_choking_judge(bindings)
        outcomes = optimize(
            self._write(tmp_path),
            samples_per_iteration=2,
            optimizations_dir=tmp_path / "o",
            emit=False,
            bindings=bindings,
        )
        outcome = outcomes[0]
        assert outcome.defect is not None
        assert outcome.record is None
        assert outcome.path is None
        assert not (tmp_path / "o").exists() or not list((tmp_path / "o").rglob("*.yaml"))
