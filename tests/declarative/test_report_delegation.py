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
from baseltest.declarative._parser import load_contract

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
        refusal = capsys.readouterr().err
        # Both routes to a renderer are named, because either would fix it.
        assert "does not carry one" in refusal
        assert "platform wheel" in refusal
        assert "github.com/mavai-org/mavai/releases" in refusal
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
        diagnostic = capsys.readouterr().err
        assert "no report was written" in diagnostic
        # Said where a run happened, so the reader is not left wondering
        # whether their samples were wasted along with the page.
        assert "the run itself is unaffected" in diagnostic


class TestReportVerb:
    """``basel report <kind> [contract]``: the second stage, on its own.

    A reader does not always want the page at the moment the samples are
    drawn. Asking later must produce what asking during the run would have,
    over the same artefacts, without invoking anything.
    """

    @pytest.fixture
    def rendered(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        """Records the argument vectors handed to the renderer."""
        vectors: list[list[str]] = []

        class Completed:
            returncode = 0

        def fake_run(vector: list[str], **_: object) -> Completed:
            vectors.append(vector)
            return Completed()

        monkeypatch.setattr(_report, "locate_renderer", lambda: "mavai")
        monkeypatch.setattr(_report.subprocess, "run", fake_run)
        return vectors

    def test_it_reports_over_the_directory_the_run_wrote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "explorations").mkdir(parents=True)

        assert main(["report", "explore"]) == 0

        assert rendered == [["mavai", "explore", str(Path("_baseltest/explorations"))]]

    def test_without_an_output_the_report_goes_to_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        """Pipeable, like everything else the family prints."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "explorations").mkdir(parents=True)

        main(["report", "explore"])

        assert "-o" not in rendered[0]

    def test_an_output_is_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "explorations").mkdir(parents=True)

        main(["report", "explore", "-o", "page.html"])

        assert rendered[0][-2:] == ["-o", "page.html"]

    def test_the_report_type_follows_the_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        """The same mapping the run verbs use — one vocabulary, not two."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "explorations").mkdir(parents=True)
        (tmp_path / "_baseltest" / "optimizations").mkdir(parents=True)

        main(["report", "explore"])
        main(["report", "optimize"])
        main(["report", "test"])
        main(["report", "measure"])

        assert [vector[1] for vector in rendered] == ["explore", "optimize", "verdict", "measure"]

    def test_a_flat_kind_is_reported_over_the_directory_that_groups_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        """Verdicts are written flat, so their directory is the grouping."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "verdicts").mkdir(parents=True)

        main(["report", "test"])

        assert rendered[0][2] == str(Path("_baseltest"))

    def test_nothing_written_is_not_a_report_that_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(_report, "locate_renderer", lambda: "mavai")

        code = main(["report", "explore"])

        refused = capsys.readouterr().err
        assert code == 2
        assert "no explore artefacts" in refused
        # The command that would fill it, so the reader is not left guessing.
        assert "basel explore" in refused

    def test_a_contract_narrows_a_kind_written_per_contract(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rendered: list[list[str]]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path)
        # The directory the writer would have made: the contract's own id,
        # read from the file rather than assumed by the caller.
        identity = load_contract(contract).contract
        (tmp_path / "_baseltest" / "explorations" / identity).mkdir(parents=True)

        assert main(["report", "explore", str(contract)]) == 0

        assert rendered[0][2] == str(Path("_baseltest/explorations") / identity)

    def test_a_contract_cannot_narrow_a_flat_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Refused, never ignored.

        Verdicts carry the contract in the filename, and selecting them by
        that would mean reading a naming convention. A reader who named a
        contract and silently got every contract would believe a report that
        is not about what they asked for.
        """
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path)
        (tmp_path / "_baseltest" / "verdicts").mkdir(parents=True)
        monkeypatch.setattr(_report, "locate_renderer", lambda: "mavai")

        code = main(["report", "test", str(contract)])

        assert code == 2
        assert "cannot narrow this report" in capsys.readouterr().err

    def test_no_renderer_refuses_before_reading_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(_report, "locate_renderer", lambda: None)

        code = main(["report", "explore"])

        assert code == 2
        assert "does not carry one" in capsys.readouterr().err

    def test_a_failed_render_is_the_verb_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike a run, drawing the report IS what this verb was asked to do."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "_baseltest" / "explorations").mkdir(parents=True)

        class Completed:
            returncode = 3

        monkeypatch.setattr(_report, "locate_renderer", lambda: "mavai")
        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Completed())

        assert main(["report", "explore"]) == 1


def _fake_executable(path: Path) -> Path:
    """A file that passes the executable test, standing in for the renderer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


class TestRendererResolution:
    """Which renderer an installation uses, and in what order it looks.

    An installation may carry its own renderer (a platform wheel bundles
    one), or find the family's on PATH, or have none at all. The order is
    the precedence, and the override answers to nobody.
    """

    def test_the_override_wins_over_everything_else(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stated = _fake_executable(tmp_path / "elsewhere" / "mavai")
        monkeypatch.setattr(_report, "bundled_renderer", lambda: str(tmp_path / "bundled"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: str(tmp_path / "on-path"))
        monkeypatch.setenv(_report.RENDERER_OVERRIDE, str(stated))

        assert _report.locate_renderer() == str(stated)

    def test_an_override_naming_nothing_is_not_a_silent_fall_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller who names a renderer must not quietly get a different one."""
        monkeypatch.setattr(_report, "bundled_renderer", lambda: str(tmp_path / "bundled"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: str(tmp_path / "on-path"))
        monkeypatch.setenv(_report.RENDERER_OVERRIDE, str(tmp_path / "absent"))

        assert _report.locate_renderer() is None

    def test_the_bundled_renderer_is_preferred_to_one_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundled = _fake_executable(tmp_path / "scripts" / _report.RENDERER)
        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "scripts"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: "/somewhere/else/mavai")

        assert _report.locate_renderer() == str(bundled)

    def test_without_a_bundled_renderer_path_still_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route every installation had before wheels carried a renderer."""
        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "empty"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: "/usr/local/bin/mavai")

        assert _report.locate_renderer() == "/usr/local/bin/mavai"

    def test_an_installation_carrying_none_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "empty"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: None)

        assert _report.locate_renderer() is None
        assert "does not carry one" in _report.RENDERER_MISSING

    def test_a_directory_is_not_a_renderer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scripts directory exists on every installation; the file need not."""
        (tmp_path / "scripts" / _report.RENDERER).mkdir(parents=True)
        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "scripts"))

        assert _report.bundled_renderer() is None


class TestRendererDisclosure:
    """``basel --version`` states the renderer this build would use."""

    def test_a_bundled_renderer_is_named_as_bundled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundled = _fake_executable(tmp_path / "scripts" / _report.RENDERER)

        class Stated:
            returncode = 0
            stdout = "mavai 9.9.9\n"

        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(bundled.parent))
        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Stated())

        assert _report.renderer_disclosure() == "mavai 9.9.9 (bundled)"

    def test_one_found_on_path_is_named_by_its_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Stated:
            returncode = 0
            stdout = "mavai 9.9.9\n"

        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "empty"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: "/usr/local/bin/mavai")
        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Stated())

        assert _report.renderer_disclosure() == "mavai 9.9.9 (/usr/local/bin/mavai)"

    def test_a_renderer_that_will_not_state_its_version_is_still_disclosed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming what will be run matters more than the version string."""

        class Stated:
            returncode = 1
            stdout = ""

        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "empty"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: "/usr/local/bin/mavai")
        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Stated())

        assert "version unstated" in _report.renderer_disclosure()

    def test_no_renderer_is_disclosed_as_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_report.RENDERER_OVERRIDE, raising=False)
        monkeypatch.setattr(_report.sysconfig, "get_path", lambda _: str(tmp_path / "empty"))
        monkeypatch.setattr(_report.shutil, "which", lambda _: None)

        assert _report.renderer_disclosure() == "no mavai report renderer (see --html-report)"


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
        assert "no report was written to" in failure
        # The run-safety clause belongs to the run path, which knows there
        # was a run; `basel report` has no run to leave unaffected.
        assert "the run itself is unaffected" not in failure

    def test_a_report_drawn_to_stdout_names_no_destination(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Completed:
            returncode = 2

        monkeypatch.setattr(_report.subprocess, "run", lambda *a, **k: Completed())

        failure = _report.render("mavai", "explore", tmp_path, None)

        assert failure is not None
        assert "no report was drawn" in failure
