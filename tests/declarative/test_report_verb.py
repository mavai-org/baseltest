"""The report verb: post-hoc rendering from persisted artefacts, exit semantics."""

from pathlib import Path
from typing import Any

from baseltest.declarative._cli import main


def write_contract(tmp_path: Path) -> Path:
    (tmp_path / "mavai-bindings.py").write_text(
        "from baseltest.declarative import Bindings\n"
        "bindings = Bindings()\n"
        "@bindings.binding('svc')\n"
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

    def test_report_explore_points_to_the_family_tool(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["report", "explore"]) == 2
        err = capsys.readouterr().err
        assert "mavai explore <dir> [-o report.html]" in err
        assert "https://github.com/mavai-org/mavai/releases" in err
        assert not (tmp_path / "_baseltest" / "reports").exists()

    def test_explore_html_report_flag_points_to_the_family_tool(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path)
        assert main(["explore", str(contract), "--html-report", "comparison.html"]) == 2
        err = capsys.readouterr().err
        assert "mavai explore <dir> [-o report.html]" in err
        assert not (tmp_path / "comparison.html").exists()
        assert not (tmp_path / "_baseltest" / "explorations").exists()  # refused before sampling

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
