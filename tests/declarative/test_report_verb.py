"""The report verb: post-hoc rendering from persisted artefacts, exit semantics."""

from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._registry import clear_registries

_EXPLORATION = """\
schemaVersion: "punit-spec-1"
useCaseId: "svc"
generatedAt: "2026-07-09T12:00:00+00:00"
factors:
  "model": "{model}"
execution:
  samplesPlanned: 5
  samplesExecuted: 5
  terminationReason: "COMPLETED"
statistics:
  observed: {rate}
  successes: {successes}
  failures: {failures}
cost:
  totalTimeMs: 2500
  avgTimePerSampleMs: {avg}
latency:
  basis: "passing-samples"
  contributingSamples: {successes}
  totalSamples: 5
  p50Ms: {p50}
  sortedPassingLatenciesMs:
{vector}
"""


def write_variant(root: Path, model: str, rate: float, successes: int, p50: int, avg: int) -> None:
    latencies = [p50 - 2, p50 - 1, p50, p50 + 1, p50 + 2][:successes]
    vector = "\n".join(f"    - {v}" for v in latencies)
    (root / "svc").mkdir(parents=True, exist_ok=True)
    (root / "svc" / f"model-{model}.yaml").write_text(
        _EXPLORATION.format(
            model=model,
            rate=rate,
            successes=successes,
            failures=5 - successes,
            avg=avg,
            p50=p50,
            vector=vector,
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def fresh_registries() -> Any:
    clear_registries()
    yield
    clear_registries()


def write_contract(tmp_path: Path) -> Path:
    (tmp_path / "mavai-bindings.py").write_text(
        "from baseltest.declarative import binding\n"
        "@binding('svc')\n"
        "def invoke(value: str) -> str:\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        "format: mavai-contract/1\n"
        "contract: reportable\n"
        "service: svc\n"
        "criteria:\n"
        "  - threshold: 0.5\n"
        '    contains: "ok"\n'
        'inputs: ["a"]\n',
        encoding="utf-8",
    )
    return contract


class TestReportVerb:
    def test_report_test_renders_from_persisted_verdicts(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["test", str(write_contract(tmp_path)), "--samples", "10"]) == 0
        assert main(["report", "test"]) == 0
        out = capsys.readouterr().out
        assert "report written: _baseltest/reports/test.html" in out
        html = (tmp_path / "_baseltest" / "reports" / "test.html").read_text(encoding="utf-8")
        assert "basel Test Report" in html and "reportable" in html

    def test_report_explore_renders_from_artefacts(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "_baseltest" / "explorations"
        write_variant(root, "a", rate=1.0, successes=5, p50=100, avg=100)
        write_variant(root, "b", rate=0.8, successes=4, p50=200, avg=210)
        assert main(["report", "explore"]) == 0
        html = (tmp_path / "_baseltest" / "reports" / "explorations.html").read_text(
            encoding="utf-8"
        )
        assert "basel Exploration Comparison" in html and "Leaderboard" in html

    def test_report_measure_is_reserved(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["report", "measure"]) == 2
        assert "no measure report type exists yet" in capsys.readouterr().err

    def test_nothing_to_render_aborts_friendly(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["report", "test"]) == 2
        err = capsys.readouterr().err
        assert "no verdict records found" in err and "basel test" in err
        assert main(["report", "explore"]) == 2
        assert "no exploration artefacts found" in capsys.readouterr().err
        assert not (tmp_path / "_baseltest" / "reports").exists()

    def test_out_option_relocates_the_report(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["test", str(write_contract(tmp_path)), "--samples", "10"]) == 0
        assert main(["report", "test", "--out", "custom/r.html"]) == 0
        assert (tmp_path / "custom" / "r.html").is_file()

    def test_inline_flag_and_post_hoc_verb_share_the_renderer(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path)
        assert main(["test", str(contract), "--samples", "10", "--html-report", "inline.html"]) == 0
        assert main(["report", "test"]) == 0
        strip = lambda text: [  # noqa: E731 - timestamps differ; structure must not
            line
            for line in text.splitlines()
            if "Generated" not in line and "elapsed" not in line.lower() and "ms</td>" not in line
        ]
        inline = strip((tmp_path / "inline.html").read_text(encoding="utf-8"))
        posthoc = strip(
            (tmp_path / "_baseltest" / "reports" / "test.html").read_text(encoding="utf-8")
        )
        assert inline == posthoc
