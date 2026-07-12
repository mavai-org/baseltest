"""Risk-driven run sizing end-to-end: every mode of the ``test`` verb.

Each test drives the real CLI (``main``) against a deterministic simulated
service, with a baseline measured through the real ``measure`` verb first.
Interactive sessions are scripted by standing in for the terminal (a fake
TTY flag and a queued ``input``).
"""

import json
import sys
import types
from pathlib import Path

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._registry import clear_registries
from baseltest.statistics import required_samples_for_power


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


BINDINGS = """
from itertools import count

from baseltest.declarative import binding

_calls = count(1)


@binding('sized-svc')
def invoke(value: str) -> str:
    n = next(_calls)
    ok = "ok" if n % 10 else "bad"        # 90% pass criterion
    extra = " extra" if n % 5 else ""     # 80% pass criterion
    return ok + extra
"""

ONE_CRITERION = """
format: mavai-contract/1
contract: sized-one
service: sized-svc
criteria:
  - name: keeps-up
    contains: "ok"
inputs: ["a"]
"""

TWO_CRITERIA = """
format: mavai-contract/1
contract: sized-two
service: sized-svc
criteria:
  - name: keeps-up
    contains: "ok"
  - name: stays-rich
    contains: "extra"
inputs: ["a"]
"""

# The deterministic service rates and the oracle-locked requirements they
# imply (tolerance 0.84 against 0.9 governs over 0.7 against 0.8).
REQUIRED_FOR_MAIN_CLAIM = required_samples_for_power(0.9, 0.84, 0.95, 0.8)


def prepare(tmp_path: Path, monkeypatch, contract_text: str) -> Path:  # type: ignore[no-untyped-def]
    """Write the bindings and contract, chdir, and measure the baseline."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mavai-bindings.py").write_text(BINDINGS, encoding="utf-8")
    contract = tmp_path / "contract.yaml"
    contract.write_text(contract_text, encoding="utf-8")
    assert main(["measure", str(contract), "--samples", "200"]) == 0
    return contract


def fake_tty(monkeypatch, answers: list[str]) -> None:  # type: ignore[no-untyped-def]
    """Stand in for an interactive terminal with queued answers."""
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    queue = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(queue))


class TestFullySpecified:
    def test_flags_compute_the_run_size_and_run_without_prompts(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        code = main(
            ["test", str(contract), "--tolerate", "84", "--confidence", "95", "--no-verdict-xml"]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert (
            f"This test needs {REQUIRED_FOR_MAIN_CLAIM} samples "
            "(computed from your declared tolerance)." in out
        )
        # The title line carries n and its provenance; no separate run-plan line.
        assert f"n = {REQUIRED_FOR_MAIN_CLAIM}" not in out
        assert "confident the true pass rate is at least" in out
        assert "catch a genuine drop to 84% about 80% of the time" in out

    def test_contract_keys_size_the_run_with_no_flags(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(
            tmp_path,
            monkeypatch,
            ONE_CRITERION.replace("name: keeps-up", "name: keeps-up\n    tolerate: 0.84"),
        )
        assert main(["test", str(contract), "--no-verdict-xml"]) == 0
        assert (
            f"This test needs {REQUIRED_FOR_MAIN_CLAIM} samples "
            "(computed from your declared tolerance)." in capsys.readouterr().out
        )

    def test_flag_overrides_the_contract_key(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(
            tmp_path,
            monkeypatch,
            ONE_CRITERION.replace("name: keeps-up", "name: keeps-up\n    tolerate: 0.7"),
        )
        assert main(["test", str(contract), "--tolerate", "0.84", "--no-verdict-xml"]) == 0
        # The flag's tighter tolerance governs, not the key's cheaper one.
        assert (
            f"This test needs {REQUIRED_FOR_MAIN_CLAIM} samples "
            "(computed from your declared tolerance)." in capsys.readouterr().out
        )

    def test_statistical_jargon_stays_out_of_the_output(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--tolerate", "84", "--no-verdict-xml"]) == 0
        out = capsys.readouterr().out.lower()
        for jargon in ("wilson", "alpha", "beta", "z-score", "power analysis"):
            assert jargon not in out


class TestMultiCriterion:
    def test_governing_size_is_the_largest_per_criterion_requirement(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, TWO_CRITERIA)
        code = main(
            [
                "test",
                str(contract),
                "--tolerate",
                "keeps-up=0.84",
                "--tolerate",
                "stays-rich=0.7",
                "--no-verdict-xml",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert (
            f"This test needs {REQUIRED_FOR_MAIN_CLAIM} samples "
            "(computed from your declared tolerances)." in out
        )
        # The sizing table: header, one row per criterion, governing marked.
        assert "tolerates" in out and "a pass proves" in out and "needs alone" in out
        lines = out.splitlines()
        governing_row = next(line for line in lines if "keeps-up" in line and "←" in line)
        assert "84%" in governing_row
        assert governing_row.endswith("← sets the run size")
        other_row = next(line for line in lines if "stays-rich" in line and "%" in line)
        assert "70%" in other_row and "←" not in other_row

    def test_bare_tolerate_against_several_criteria_is_refused_naming_them(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, TWO_CRITERIA)
        assert main(["test", str(contract), "--tolerate", "0.84"]) == 2
        err = capsys.readouterr().err
        assert "keeps-up" in err and "stays-rich" in err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_unknown_criterion_in_tolerate_flag_is_refused(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, TWO_CRITERIA)
        assert main(["test", str(contract), "--tolerate", "ghost=0.8"]) == 2
        assert "ghost" in capsys.readouterr().err


class TestInteractiveMode:
    def test_two_answers_size_confirm_and_run(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        # confidence preset (Standard), lowest acceptable rate, confirm run.
        fake_tty(monkeypatch, ["1", "84", ""])
        assert main(["test", str(contract), "--no-verdict-xml"]) == 0
        out = capsys.readouterr().out
        assert "proven baseline pass rate for criterion keeps-up is 90%" in out
        assert "How sure do you want to be" in out
        assert (
            f"This test needs {REQUIRED_FOR_MAIN_CLAIM} samples "
            "(computed from your declared tolerance)." in out
        )

    def test_invalid_answers_are_re_asked(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        # A rate above the baseline and a non-number are corrected, then valid.
        fake_tty(monkeypatch, ["1", "95", "many", "84", ""])
        assert main(["test", str(contract), "--no-verdict-xml"]) == 0
        out = capsys.readouterr().out
        assert "must be below the proven baseline" in out
        assert "please try again" in out

    def test_declining_the_confirmation_exits_two_without_sampling(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        fake_tty(monkeypatch, ["1", "84", "n"])
        assert main(["test", str(contract)]) == 2
        assert "declined" in capsys.readouterr().err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_declared_confidence_is_not_asked_again(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION + "confidence: 0.95\n")
        fake_tty(monkeypatch, ["84", ""])
        assert main(["test", str(contract), "--no-verdict-xml"]) == 0
        assert "How sure do you want to be" not in capsys.readouterr().out


class TestNoTtyRefusal:
    def test_missing_claims_without_a_terminal_refuse_with_the_flags_named(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract)]) == 2
        err = capsys.readouterr().err
        assert "--tolerate" in err and "keeps-up" in err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_tolerate_against_a_thresholded_only_contract_is_refused(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        (tmp_path / "mavai-bindings.py").write_text(BINDINGS, encoding="utf-8")
        contract = tmp_path / "contract.yaml"
        contract.write_text(
            ONE_CRITERION.replace("name: keeps-up", "name: keeps-up\n    threshold: 0.5"),
            encoding="utf-8",
        )
        assert main(["test", str(contract), "--tolerate", "0.84"]) == 2
        assert "no baseline claim" in capsys.readouterr().err


class TestExplicitSamples:
    def test_a_strong_explicit_size_runs_with_the_explanation_and_no_confirmation(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--samples", "400", "--no-verdict-xml"]) == 0
        out = capsys.readouterr().out
        assert "You asked to run 400 samples." in out
        assert "confident the true pass rate is at least" in out
        assert "warning" not in out.lower()

    def test_a_weak_explicit_size_needs_yes_in_automation(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--samples", "30"]) == 2
        captured = capsys.readouterr()
        assert "weak test" in captured.out
        assert "--accept-weak-design" in captured.err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_yes_restores_full_automation_for_a_weak_size(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        code = main(
            ["test", str(contract), "--samples", "30", "--accept-weak-design", "--no-verdict-xml"]
        )
        assert code in (0, 1)  # judged honestly at the weak size
        assert "only catch a genuine drop" in capsys.readouterr().out

    def test_a_weak_size_against_a_declared_claim_names_the_needed_count(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(
            tmp_path,
            monkeypatch,
            ONE_CRITERION.replace("name: keeps-up", "name: keeps-up\n    tolerate: 0.84"),
        )
        fake_tty(monkeypatch, ["n"])
        code = main(["test", str(contract), "--samples", "100"])
        assert code == 2
        out = capsys.readouterr().out
        assert f"you would need about {REQUIRED_FOR_MAIN_CLAIM} tests" in out

    def test_contract_keys_with_explicit_samples_run_at_the_chosen_size(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(
            tmp_path,
            monkeypatch,
            ONE_CRITERION.replace("name: keeps-up", "name: keeps-up\n    tolerate: 0.84"),
        )
        code = main(["test", str(contract), "--samples", "400", "--no-verdict-xml"])
        assert code in (0, 1)
        out = capsys.readouterr().out
        assert "You asked to run 400 samples." in out
        assert "confident the true pass rate is at least" in out

    def test_interactive_confirmation_lets_a_weak_run_proceed(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        fake_tty(monkeypatch, ["y"])
        code = main(["test", str(contract), "--samples", "30", "--no-verdict-xml"])
        assert code in (0, 1)


class TestContradictorySizingFlags:
    def test_samples_with_tolerate_aborts_naming_both_flags(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--samples", "100", "--tolerate", "84"]) == 2
        err = capsys.readouterr().err
        assert "--samples and --tolerate are contradictory sizing instructions" in err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_samples_with_named_tolerate_form_aborts_too(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        code = main(["test", str(contract), "--samples", "100", "--tolerate", "keeps-up=0.84"])
        assert code == 2
        assert "contradictory sizing instructions" in capsys.readouterr().err

    def test_samples_with_power_aborts_naming_both_flags(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--samples", "100", "--power", "0.9"]) == 2
        err = capsys.readouterr().err
        assert "--samples and --power are contradictory sizing instructions" in err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))


class TestOverReach:
    def test_over_reach_refuses_in_automation_without_force(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--tolerate", "95"]) == 2
        captured = capsys.readouterr()
        assert "more than the evidence supports" in captured.out
        assert "--force" in captured.err
        assert not list((tmp_path / "_baseltest" / "verdicts").glob("*.xml"))

    def test_force_without_samples_still_needs_a_size(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        assert main(["test", str(contract), "--tolerate", "95", "--force"]) == 2
        assert "--samples" in capsys.readouterr().err

    def test_force_with_samples_runs_and_still_explains(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        code = main(
            [
                "test",
                str(contract),
                "--tolerate",
                "95",
                "--force",
                "--samples",
                "50",
                "--no-verdict-xml",
            ]
        )
        assert code in (0, 1)
        out = capsys.readouterr().out
        assert "more than the evidence supports" in out
        assert "You asked to run 50 samples." in out

    def test_interactive_over_reach_confirm_defaults_to_no(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        fake_tty(monkeypatch, [""])  # the default answer declines
        assert main(["test", str(contract), "--tolerate", "95"]) == 2
        assert "declined" in capsys.readouterr().err


class TestReportDisclosures:
    def test_a_downsized_run_disclosures_approach_trade_and_saving(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        report = tmp_path / "report.html"
        code = main(
            [
                "test",
                str(contract),
                "--samples",
                "50",
                "--accept-weak-design",
                "--html-report",
                str(report),
            ]
        )
        assert code in (0, 1)
        html = report.read_text(encoding="utf-8")
        assert "Run design" in html
        assert "sample-size-first" in html
        assert "This run executed 50 samples against a baseline measured over 200." in html
        assert "would only catch a drop below" in html
        assert "four times out of five" in html
        assert "less execution time" in html and "Estimates only" in html

    def test_a_risk_driven_run_disclosures_the_approach_and_claims(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        report = tmp_path / "report.html"
        code = main(["test", str(contract), "--tolerate", "84", "--html-report", str(report)])
        assert code == 0
        html = report.read_text(encoding="utf-8")
        assert "confidence-first (risk-driven)" in html
        assert f"computed n {REQUIRED_FOR_MAIN_CLAIM}" in html
        # The computed size exceeds the baseline's own 200 samples: there is
        # no downsizing trade to disclose.
        assert "only catch a drop below" not in html

    def test_the_post_hoc_report_carries_the_same_disclosures(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        inline = tmp_path / "inline.html"
        assert main(
            [
                "test",
                str(contract),
                "--samples",
                "50",
                "--accept-weak-design",
                "--html-report",
                str(inline),
            ]
        ) in (0, 1)
        assert main(["report", "test"]) == 0
        post_hoc = (tmp_path / "_baseltest" / "reports" / "test.html").read_text(encoding="utf-8")
        assert "Run design" in post_hoc
        assert "would only catch a drop below" in post_hoc
        assert "less execution time" in post_hoc


class TestJsonMode:
    def test_json_emits_the_sizing_block_and_runs_silently(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, TWO_CRITERIA)
        capsys.readouterr()  # drain the measure run's output
        code = main(
            [
                "test",
                str(contract),
                "--tolerate",
                "keeps-up=0.84",
                "--tolerate",
                "stays-rich=0.7",
                "--json",
                "--no-verdict-xml",
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["approach"] == "confidence-first (risk-driven)"
        assert payload["governing"] == {
            "criterion": "keeps-up",
            "samples": REQUIRED_FOR_MAIN_CLAIM,
        }
        assert payload["requiredSamples"] == REQUIRED_FOR_MAIN_CLAIM
        assert {row["criterion"] for row in payload["criteria"]} == {"keeps-up", "stays-rich"}
        for row in payload["criteria"]:
            assert set(row) == {
                "criterion",
                "baseline_rate",
                "tolerated_rate",
                "confidence",
                "required_n",
                "floor",
                "power",
            }
        assert 0 < payload["acceptanceFloor"] < 1
        assert 0 < payload["detectableDrop"] < 1
        assert "explanation" in payload

    def test_json_with_missing_claims_refuses_rather_than_prompting(
        self, tmp_path, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        contract = prepare(tmp_path, monkeypatch, ONE_CRITERION)
        fake_tty(monkeypatch, ["should", "never", "be", "read"])
        assert main(["test", str(contract), "--json"]) == 2
        assert "--tolerate" in capsys.readouterr().err
