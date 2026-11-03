"""`zero-failures: true` (contract format, amendment 2026-11-03): parsing,
load-time refusals, instantiation, sizing, both verbs, and materialisation
through the declarative reader."""

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._materialise import materialise
from baseltest.declarative._parser import parse_contract

HEADER = """
format: mavai-contract/1
contract: greeting-never-insults
service: svc
"""


def refusal(contract: str) -> str:
    with pytest.raises(ContractConfigurationError) as caught:
        parse_contract(HEADER + contract)
    return str(caught.value)


def write_bindings(tmp_path, misses: int = 0) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "mavai-bindings.py").write_text(
        "import itertools\n"
        "from baseltest.declarative import Bindings\n"
        "bindings = Bindings()\n"
        "_counter = itertools.count()\n"
        "@bindings.binding('svc')\n"
        "def invoke(value: str) -> str:\n"
        f"    return 'go away' if next(_counter) < {misses} else 'hello'\n",
        encoding="utf-8",
    )


def write_contract(tmp_path, criteria: str, misses: int = 0):  # type: ignore[no-untyped-def]
    write_bindings(tmp_path, misses)
    contract = tmp_path / "contract.yaml"
    contract.write_text(HEADER + criteria + 'inputs: ["Alice"]\n', encoding="utf-8")
    return contract


ZERO_ONLY = """criteria:
  - name: never-insults
    zero-failures: true
    not-equals: "go away"
"""

MIXED = """criteria:
  - name: never-insults
    zero-failures: true
    not-equals: "go away"
  - name: greets
    threshold: 0.9
    contains: "hello"
"""


class TestParsing:
    def test_true_parses_as_a_zero_failures_criterion(self) -> None:
        declaration = parse_contract(HEADER + ZERO_ONLY + 'inputs: ["a"]\n')
        (criterion,) = declaration.criteria
        assert criterion.zero_failures is True
        assert criterion.threshold is None
        assert not criterion.is_empirical

    def test_false_leaves_the_criterion_as_it_was(self) -> None:
        declaration = parse_contract(
            HEADER
            + 'criteria:\n  - threshold: 0.9\n    zero-failures: false\n    contains: "x"\n'
            + 'inputs: ["a"]\n'
        )
        (criterion,) = declaration.criteria
        assert criterion.zero_failures is False and criterion.threshold == 0.9

    def test_an_absent_threshold_without_the_key_stays_empirical(self) -> None:
        declaration = parse_contract(HEADER + 'criteria:\n  - contains: "x"\ninputs: ["a"]\n')
        assert declaration.criteria[0].is_empirical

    def test_provenance_and_slack_are_allowed(self) -> None:
        declaration = parse_contract(
            HEADER
            + "criteria:\n  - zero-failures: true\n    threshold-origin: policy\n"
            + '    contract-ref: "Safety Policy v3"\n    optional-slack: 1\n'
            + '    postconditions:\n      - contains: "x"\n      - contains: "y"\n'
            + "        optional: true\n"
            + 'inputs: ["a"]\n'
        )
        (criterion,) = declaration.criteria
        assert criterion.zero_failures
        assert (criterion.threshold_origin, criterion.optional_slack) == ("policy", 1)


class TestRefusals:
    @pytest.mark.parametrize(
        ("key", "why"),
        [
            ("threshold: 0.95", "no rate to require"),
            ("tolerate: 0.9", "no baseline risk claim to protect"),
            ("confidence: 0.99", "no confidence level to set"),
        ],
    )
    def test_nothing_that_parameterises_a_rate_stands_beside_it(self, key: str, why: str) -> None:
        message = refusal(
            f'criteria:\n  - zero-failures: true\n    {key}\n    contains: "x"\ninputs: ["a"]\n'
        )
        assert why in message
        assert "drop one of the two keys" in message

    @pytest.mark.parametrize("value", ["1", '"true"', "yes"])
    def test_a_non_boolean_is_refused(self, value: str) -> None:
        # YAML 1.2: `yes` is a string, not a boolean.
        message = refusal(
            f'criteria:\n  - zero-failures: {value}\n    contains: "x"\ninputs: ["a"]\n'
        )
        assert "`zero-failures:` takes a boolean" in message


class TestTest:
    def test_a_zero_failures_only_test_without_samples_is_refused(  # type: ignore[no-untyped-def]
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, ZERO_ONLY)
        assert main(["test", str(contract)]) == 2
        err = capsys.readouterr().err
        assert "zero failures in N trials bounds nothing" in err
        assert "--samples N" in err

    def test_with_samples_no_failure_passes(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, ZERO_ONLY)
        assert main(["test", str(contract), "--samples", "30"]) == 0
        out = capsys.readouterr().out
        assert "no failure observed in 30 trials — no rate is claimed" in out
        assert "n = 30 (set via --samples)" in out

    def test_one_failure_fails(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, ZERO_ONLY, misses=1)
        assert main(["test", str(contract), "--samples", "30"]) == 1
        assert "1 of 30 trials failed" in capsys.readouterr().out

    def test_beside_a_threshold_n_is_derived_from_the_threshold(  # type: ignore[no-untyped-def]
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, MIXED)
        assert main(["test", str(contract)]) == 0
        out = capsys.readouterr().out
        # 0.9 at alpha 0.05 needs 29 samples; the zero-failures criterion adds nothing.
        assert "n = 29 (derived: criterion greets's threshold 0.9" in out
        assert "no failure observed in 29 trials" in out

    def test_smoke_intent_does_not_change_the_judgement(self, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, "intent: smoke\n" + ZERO_ONLY, misses=1)
        assert main(["test", str(contract), "--samples", "30"]) == 1
        assert "1 of 30 trials failed" in capsys.readouterr().out


class TestMeasure:
    def test_measure_records_the_count_and_an_observational_baseline(  # type: ignore[no-untyped-def]
        self, tmp_path, monkeypatch, capsys
    ):
        from ruamel.yaml import YAML

        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, ZERO_ONLY, misses=2)
        assert main(["measure", str(contract), "--samples", "20"]) == 0
        out = capsys.readouterr().out
        assert "2 of 20 trials failed — recorded, not a verdict" in out
        (path,) = (tmp_path / "_baseltest" / "baselines").glob("*.yaml")
        document = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
        criterion = document["criteria"]["never-insults"]
        assert criterion["mode"] == "observational"
        assert "observedPassRate" not in criterion

    def test_measure_assert_fails_after_recording_on_a_failure(  # type: ignore[no-untyped-def]
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        contract = write_contract(tmp_path, ZERO_ONLY, misses=1)
        assert main(["measure", str(contract), "--samples", "20", "--assert"]) == 1
        assert list((tmp_path / "_baseltest" / "baselines").glob("*.yaml"))


class TestMaterialisation:
    def test_it_emits_zero_failures_true(self) -> None:
        declaration = parse_contract(
            HEADER
            + "criteria:\n  - zero-failures: true\n    threshold-origin: policy\n"
            + '    not-equals: "go away"\ninputs: ["a"]\n'
        )
        source = materialise(declaration)
        assert "zero_failures=True," in source
        assert "threshold=" not in source
        assert "origin='policy'" in source
        compile(source, "materialised.py", "exec")
