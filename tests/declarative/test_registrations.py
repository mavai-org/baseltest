"""The mavai-bindings.py convention: discovered, imported once, refused helpfully."""

from pathlib import Path

import pytest

from baseltest.declarative import run
from baseltest.declarative._errors import TaskConfigurationError
from baseltest.declarative._registry import clear_registries
from baseltest.statistics.verdict import Verdict

TASK = """
format: mavai-task/1
task: conventioned
service: convention-service
samples: 50
inputs: ["a"]
criteria:
  - threshold: 0.5
    contains: "ok"
"""

BINDINGS = """
from baseltest.declarative import binding

@binding("convention-service")
def invoke(value: str) -> str:
    return f"ok {value}"
"""


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


def test_bindings_file_beside_task_is_discovered(tmp_path: Path) -> None:
    (tmp_path / "mavai-bindings.py").write_text(BINDINGS, encoding="utf-8")
    task = tmp_path / "task.yaml"
    task.write_text(TASK, encoding="utf-8")
    result = run(task, emit=False)
    assert result.composite is Verdict.PASS


def test_broken_bindings_file_is_a_constructive_refusal(tmp_path: Path) -> None:
    (tmp_path / "mavai-bindings.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")
    task = tmp_path / "task.yaml"
    task.write_text(TASK, encoding="utf-8")
    with pytest.raises(TaskConfigurationError, match="mavai-bindings.py"):
        run(task, emit=False)


def test_absent_bindings_file_leaves_in_process_registration_working(tmp_path: Path) -> None:
    from baseltest.declarative import binding

    @binding("convention-service")
    def invoke(value: str) -> str:
        return f"ok {value}"

    task = tmp_path / "task.yaml"
    task.write_text(TASK, encoding="utf-8")
    assert run(task, emit=False).composite is Verdict.PASS
