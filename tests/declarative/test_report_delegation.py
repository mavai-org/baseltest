"""``--html-report``: what baseltest hands to mavai, and what it never does.

baseltest renders no HTML. These assert the seam — that the renderer is
found before samples are drawn, that it receives the report type and the
directory the run wrote, and that whatever it does the verb's own exit code
is untouched.
"""

from pathlib import Path

import pytest

from baseltest.declarative import _report
from baseltest.declarative._cli import main

from .test_cli import write_contract


@pytest.fixture
def contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return write_contract(tmp_path)


class TestPreflight:
    """A report that cannot be drawn is refused before the run costs anything."""

    def test_a_missing_renderer_is_refused_before_any_sample(
        self, contract: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(_report, "locate_renderer", lambda: None)

        code = main(["test", str(contract), "--samples", "60", "--html-report", "r.html"])

        assert code == 2
        assert "not on PATH" in capsys.readouterr().err
        # The refusal precedes the run: nothing was invoked, nothing written.
        assert not (tmp_path / "_baseltest").exists()

    def test_suppressing_the_verdict_record_refuses_the_report_it_renders(
        self, contract: Path, tmp_path: Path, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        argv = ["test", str(contract), "--samples", "60"]
        code = main([*argv, "--no-verdict-xml", "--html-report", "r.html"])

        assert code == 2
        assert "--no-verdict-xml" in capsys.readouterr().err
        assert not (tmp_path / "_baseltest").exists()

    def test_no_flag_asks_nothing_of_the_renderer(
        self, contract: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def never(*args: object, **kwargs: object) -> None:
            raise AssertionError("the renderer was consulted without --html-report")

        monkeypatch.setattr(_report, "locate_renderer", never)

        assert main(["test", str(contract), "--samples", "60"]) == 0


class TestDelegation:
    """What the renderer is asked to draw."""

    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
        seen: list[tuple[str, str, str]] = []
        monkeypatch.setattr(_report, "locate_renderer", lambda: "/usr/local/bin/mavai")

        def record(renderer: str, report: str, artefacts: Path, output: Path) -> None:
            seen.append((report, artefacts.as_posix(), output.as_posix()))
            return None

        monkeypatch.setattr(_report, "render", record)
        return seen

    def test_a_test_run_asks_for_the_verdict_report_over_the_artefact_root(
        self, contract: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)

        assert main(["test", str(contract), "--samples", "60", "--html-report", "r.html"]) == 0

        # The verdicts directory is written flat, so the renderer — which
        # groups by the directory beneath the one it is given — gets its parent.
        assert seen == [("verdict", "_baseltest", "r.html")]

    def test_a_measure_run_asks_for_the_measure_report(
        self, contract: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)

        assert main(["measure", str(contract), "--samples", "40", "--html-report", "m.html"]) == 0

        assert seen == [("measure", "_baseltest", "m.html")]

    def test_the_report_type_follows_the_verb(self) -> None:
        """Every verb that writes artefacts names the report they make."""
        assert _report.REPORT_OF == {
            "test": "verdict",
            "measure": "measure",
            "explore": "explore",
            "optimize": "optimize",
        }


class TestExitCode:
    """The verb's exit code states the run, never the report."""

    def test_a_failed_render_leaves_a_passing_run_passing(
        self, contract: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(_report, "locate_renderer", lambda: "/usr/local/bin/mavai")
        monkeypatch.setattr(
            _report, "render", lambda *_: "mavai verdict exited 1: no report was written"
        )

        code = main(["test", str(contract), "--samples", "60", "--html-report", "r.html"])

        assert code == 0
        assert "no report was written" in capsys.readouterr().err


class TestRendererInvocation:
    """The argument vector handed to the renderer."""

    def test_it_is_a_fixed_vector_with_no_shell(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv: list[str] = []
        keywords: dict[str, object] = {}

        class Completed:
            returncode = 0

        def fake_run(vector: list[str], **kwargs: object) -> Completed:
            argv.extend(vector)
            keywords.update(kwargs)
            return Completed()

        monkeypatch.setattr(_report.subprocess, "run", fake_run)

        failure = _report.render("mavai", "explore", tmp_path / "arte", tmp_path / "out" / "r.html")

        assert failure is None
        assert argv == [
            "mavai",
            "explore",
            str(tmp_path / "arte"),
            "-o",
            str(tmp_path / "out" / "r.html"),
        ]
        assert "shell" not in keywords
        # The destination's directory is made ready for the renderer.
        assert (tmp_path / "out").is_dir()

    def test_a_non_zero_exit_becomes_a_diagnostic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Completed:
            returncode = 1

        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Completed())

        failure = _report.render("mavai", "verdict", tmp_path, tmp_path / "r.html")

        assert failure is not None
        assert "exited 1" in failure
        assert "the run itself is unaffected" in failure
