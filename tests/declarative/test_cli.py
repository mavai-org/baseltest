"""The CLI verbs: exit-code semantics, including the opt-in measure assertion."""

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._registry import clear_registries


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


class TestMeasureAssertion:
    def _task(self, tmp_path, threshold="0.5", samples=100):  # type: ignore[no-untyped-def]
        (tmp_path / "mavai-bindings.py").write_text(
            "from baseltest.declarative import binding\n"
            "@binding('svc')\n"
            "def invoke(value: str) -> str:\n"
            "    return 'ok'\n",
            encoding="utf-8",
        )
        task = tmp_path / "task.yaml"
        task.write_text(
            f"""
format: mavai-task/1
task: assert-example
service: svc
samples: {samples}
criteria:
  - threshold: {threshold}
    contains: "ok"
inputs: ["a"]
""",
            encoding="utf-8",
        )
        return task

    def test_plain_measure_exits_zero_even_when_bar_unmet(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        task = self._task(tmp_path, threshold="0.999", samples=100)
        task.write_text(task.read_text().replace('contains: "ok"', 'contains: "nope"'))
        assert main(["measure", str(task)]) == 0

    def test_assert_fails_after_recording_when_bar_unmet(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        task = self._task(tmp_path, threshold="0.5", samples=100)
        task.write_text(task.read_text().replace('contains: "ok"', 'contains: "nope"'))
        code = main(["measure", str(task), "--assert"])
        assert code == 1
        assert list((tmp_path / "baselines").glob("*.yaml"))  # persisted before assertion
        assert "failing after recording" in capsys.readouterr().err

    def test_assert_passes_when_bar_met(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        task = self._task(tmp_path, threshold="0.5", samples=100)
        assert main(["measure", str(task), "--assert"]) == 0

    def test_assert_distinguishes_unsupportable(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        # 20 samples can never support 0.99: unsupportable, exit 3, still persisted
        task = self._task(tmp_path, threshold="0.99", samples=20)
        code = main(["measure", str(task), "--assert"])
        assert code == 3
        assert list((tmp_path / "baselines").glob("*.yaml"))
        assert "unsupportable" in capsys.readouterr().err


class TestSampleLimit:
    def _task(self, tmp_path):  # type: ignore[no-untyped-def]
        (tmp_path / "mavai-bindings.py").write_text(
            "from baseltest.declarative import binding\n"
            "@binding('svc')\n"
            "def invoke(value: str) -> str:\n"
            "    return 'ok'\n",
            encoding="utf-8",
        )
        task = tmp_path / "task.yaml"
        task.write_text(
            """
format: mavai-task/1
task: limited
service: svc
samples: 1000
criteria:
  - threshold: 0.5
    contains: "ok"
inputs: ["a"]
""",
            encoding="utf-8",
        )
        return task

    def test_samples_flag_overrides_the_file(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        assert main(["test", str(self._task(tmp_path)), "--samples", "60"]) == 0
        assert "60 of 60 responses" in capsys.readouterr().out

    def test_override_too_small_for_the_bar_is_refused(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        task = self._task(tmp_path)
        task.write_text(task.read_text().replace("threshold: 0.5", "threshold: 0.99"))
        assert main(["test", str(task), "--samples", "50"]) == 2
        assert "cannot support" in capsys.readouterr().err

    def test_samples_flag_applies_to_measure_too(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        assert main(["measure", str(self._task(tmp_path)), "--samples", "40"]) == 0
        assert "40 of 40 responses" in capsys.readouterr().out
