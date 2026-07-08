"""The CLI verbs: exit-code semantics, sample sizing, the derivation gate."""

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._registry import clear_registries


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


def write_contract(tmp_path, threshold="0.5", inputs='["a"]', name="assert-example"):  # type: ignore[no-untyped-def]
    (tmp_path / "mavai-bindings.py").write_text(
        "from baseltest.declarative import binding\n"
        "@binding('svc')\n"
        "def invoke(value: str) -> str:\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        f"""
format: mavai-contract/1
contract: {name}
service: svc
criteria:
  - threshold: {threshold}
    contains: "ok"
inputs: {inputs}
""",
        encoding="utf-8",
    )
    return contract


class TestMeasureAssertion:
    def test_plain_measure_exits_zero_even_when_bar_unmet(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.999")
        contract.write_text(contract.read_text().replace('contains: "ok"', 'contains: "nope"'))
        assert main(["measure", str(contract), "--samples", "100"]) == 0

    def test_assert_fails_after_recording_when_bar_unmet(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.5")
        contract.write_text(contract.read_text().replace('contains: "ok"', 'contains: "nope"'))
        code = main(["measure", str(contract), "--samples", "100", "--assert"])
        assert code == 1
        assert list(
            (tmp_path / "_baseltest" / "baselines").glob("*.yaml")
        )  # persisted before assertion
        assert "failing after recording" in capsys.readouterr().err

    def test_assert_passes_when_bar_met(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.5")
        assert main(["measure", str(contract), "--samples", "100", "--assert"]) == 0

    def test_assert_distinguishes_unsupportable(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        # 20 samples can never support 0.99: unsupportable, exit 3, still persisted
        contract = write_contract(tmp_path, threshold="0.99")
        code = main(["measure", str(contract), "--samples", "20", "--assert"])
        assert code == 3
        assert list((tmp_path / "_baseltest" / "baselines").glob("*.yaml"))
        assert "unsupportable" in capsys.readouterr().err


class TestSampleSizing:
    def test_samples_flag_sizes_the_run(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        assert main(["test", str(write_contract(tmp_path)), "--samples", "60"]) == 0
        out = capsys.readouterr().out
        assert "60 of 60 responses" in out
        assert "n = 60 (set via --samples)" in out

    def test_flag_too_small_for_the_bar_is_refused(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        # The gate did not weaken the feasibility check.
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.99")
        assert main(["test", str(contract), "--samples", "50"]) == 2
        assert "cannot support" in capsys.readouterr().err

    def test_samples_flag_applies_to_measure_too(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        assert main(["measure", str(write_contract(tmp_path)), "--samples", "40"]) == 0
        assert "40 of 40 responses" in capsys.readouterr().out

    def test_measure_without_samples_is_a_constructive_refusal(  # type: ignore[no-untyped-def]
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        assert main(["measure", str(write_contract(tmp_path))]) == 2
        err = capsys.readouterr().err
        assert "--samples" in err
        assert "1000" in err  # the baseline-grade recommendation, visible
        assert not list((tmp_path / "_baseltest").glob("**/*.yaml"))  # zero invocations

    def test_withdrawn_file_key_is_refused_naming_the_flag(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path)
        contract.write_text(
            contract.read_text().replace("service: svc", "service: svc\nsamples: 50")
        )
        assert main(["test", str(contract)]) == 2
        assert "--samples" in capsys.readouterr().err


class TestDerivationGate:
    def test_modest_bar_derives_and_runs(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        assert main(["test", str(write_contract(tmp_path, threshold="0.8"))]) == 0
        out = capsys.readouterr().out
        assert "derived" in out and "0.8" in out  # the run-plan line, before results

    def test_silently_derived_n_above_the_limit_is_refused(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.99")
        assert main(["test", str(contract)]) == 2
        err = capsys.readouterr().err
        assert "derive silently" in err
        assert "--samples" in err and "intent: smoke" in err
        assert not list((tmp_path / "_baseltest").glob("**/*.yaml"))  # zero invocations

    def test_an_explicit_flag_above_the_limit_sails_through(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        # The gate binds the number nobody typed; a typed number of any size runs.
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.99")
        assert main(["test", str(contract), "--samples", "400", "--no-verdict-xml"]) == 0

    def test_smoke_intent_defaults_small_with_no_gate(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, threshold="0.99")
        contract.write_text(
            contract.read_text().replace("service: svc", "service: svc\nintent: smoke")
        )
        assert main(["test", str(contract), "--no-verdict-xml"]) == 1  # honest FAIL at n=5
        out = capsys.readouterr().out
        assert "n = 5 (default; use --samples to size the run)" in out

    def test_defaults_are_independent_of_input_count(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        # Inputs are a pool the engine cycles over, never a work queue:
        # a many-input contract sizes exactly like a small one.
        monkeypatch.chdir(tmp_path)
        many = "[" + ", ".join(f'"input {i}"' for i in range(200)) + "]"
        few = write_contract(tmp_path, threshold="0.8", inputs='["a", "b"]', name="few")
        assert main(["test", str(few), "--no-verdict-xml"]) == 0
        line_few = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("n = ")
        )
        many_contract = write_contract(tmp_path, threshold="0.8", inputs=many, name="many")
        assert main(["test", str(many_contract), "--no-verdict-xml"]) == 0
        line_many = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("n = ")
        )
        assert line_few == line_many
        assert "exceed" not in line_many  # no remark on samples vs inputs


class TestProgressLine:
    def test_progress_overwrites_while_sampling_and_persists_on_completion(
        self, monkeypatch, capsys
    ):  # type: ignore[no-untyped-def]
        import sys

        from baseltest.declarative._runner import _tty_progress

        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        on_sample = _tty_progress("provider-openai_model-gpt-4o-mini")
        assert on_sample is not None
        on_sample(1, 5)
        on_sample(5, 5)
        err = capsys.readouterr().err
        # Mid-run updates overwrite in place; the completed line ends with a
        # newline so it survives the next configuration's progress.
        assert "sampling provider-openai_model-gpt-4o-mini: 1/5\r" in err
        assert err.endswith("sampled provider-openai_model-gpt-4o-mini: 5/5\n")

    def test_no_progress_callback_off_a_terminal(self):  # type: ignore[no-untyped-def]
        from baseltest.declarative._runner import _tty_progress

        assert _tty_progress("anything") is None  # captured stderr is not a TTY
