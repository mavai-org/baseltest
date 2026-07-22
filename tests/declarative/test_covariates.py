"""Binding-declared covariates: registration, recording, and drift refusal."""

import sys
from pathlib import Path

import pytest

from baseltest.declarative import Bindings, run
from baseltest.declarative._cli import main
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._registry import Registry
from baseltest.engine import Verdict


def write_contract(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


EMPIRICAL_CONTRACT = """
format: mavai-contract/1
contract: pipeline-stays-grounded
service: pipeline
criteria:
  - name: grounded
    contains: "ok"
inputs: ["a", "b"]
"""


def register_pipeline(registry: Bindings | Registry, covariates: dict[str, str] | None) -> None:
    @registry.binding("pipeline", covariates=covariates)
    def invoke(value: str) -> str:
        return f"ok {value}"


class TestRegistration:
    def test_declared_covariates_are_resolvable(self) -> None:
        registry = Registry()
        register_pipeline(registry, {"ontology": "abc123", "judge": "v2"})
        assert registry.binding_covariates("pipeline") == {"ontology": "abc123", "judge": "v2"}

    def test_omitted_covariates_resolve_empty(self) -> None:
        registry = Registry()
        register_pipeline(registry, None)
        assert registry.binding_covariates("pipeline") == {}

    def test_reserved_key_refused_naming_the_key(self) -> None:
        for reserved in ("binding", "runMode", "serviceType", "taskFile", "taskFormat"):
            with pytest.raises(ContractConfigurationError, match=reserved):
                Registry().binding("svc", covariates={reserved: "x"})

    def test_non_string_value_refused_with_the_type_named(self) -> None:
        with pytest.raises(ContractConfigurationError, match="int"):
            Registry().binding("svc", covariates={"catalogue-size": 40})  # type: ignore[dict-item]

    def test_empty_key_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="non-empty"):
            Registry().binding("svc", covariates={"": "x"})

    def test_covariates_of_an_unregistered_binding_are_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="@bindings.binding"):
            Registry().binding_covariates("ghost")


class TestBaselineRecording:
    def test_measure_persists_covariates_in_provenance(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_pipeline(bindings, {"ontology": "abc123"})
        run(
            write_contract(tmp_path, EMPIRICAL_CONTRACT),
            mode="measure",
            samples=50,
            baseline_dir=tmp_path / "baselines",
            emit=False,
            bindings=bindings,
        )
        (artefact,) = (tmp_path / "baselines").glob("*.yaml")
        content = artefact.read_text(encoding="utf-8")
        assert '"ontology": "abc123"' in content

    def test_test_resolves_the_baseline_under_matching_covariates(self, tmp_path: Path) -> None:
        bindings = Bindings()
        register_pipeline(bindings, {"ontology": "abc123"})
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(
            contract,
            mode="measure",
            samples=200,
            baseline_dir=tmp_path / "b",
            emit=False,
            bindings=bindings,
        )
        result = run(
            contract,
            mode="test",
            samples=200,
            baseline_dir=tmp_path / "b",
            emit=False,
            bindings=bindings,
        )
        assert result.composite is Verdict.PASS
        assert result.criterion_results[0].criterion.provenance.origin == "empirical"


class TestDriftRefusal:
    def test_drifted_covariate_refuses_naming_the_key(self, tmp_path: Path) -> None:
        measure_bindings = Bindings()
        register_pipeline(measure_bindings, {"ontology": "abc123"})
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(
            contract,
            mode="measure",
            samples=50,
            baseline_dir=tmp_path / "b",
            emit=False,
            bindings=measure_bindings,
        )
        drifted_bindings = Bindings()
        register_pipeline(drifted_bindings, {"ontology": "def456"})
        with pytest.raises(ContractConfigurationError) as refusal:
            run(
                contract,
                mode="test",
                baseline_dir=tmp_path / "b",
                emit=False,
                bindings=drifted_bindings,
            )
        assert "different configuration" in str(refusal.value)
        assert "ontology" in str(refusal.value)

    def test_added_covariate_refuses_naming_the_key(self, tmp_path: Path) -> None:
        measure_bindings = Bindings()
        register_pipeline(measure_bindings, None)
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(
            contract,
            mode="measure",
            samples=50,
            baseline_dir=tmp_path / "b",
            emit=False,
            bindings=measure_bindings,
        )
        drifted_bindings = Bindings()
        register_pipeline(drifted_bindings, {"judge": "v2"})
        with pytest.raises(ContractConfigurationError, match="judge"):
            run(
                contract,
                mode="test",
                baseline_dir=tmp_path / "b",
                emit=False,
                bindings=drifted_bindings,
            )

    def test_sizing_refusal_names_the_drifted_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The risk-driven sizing conversation resolves the same baseline the
        # run would judge against; its refusal must carry the drift reason,
        # never flatten it into a bare "no baseline".
        bindings = """
from baseltest.declarative import Bindings

bindings = Bindings()

@bindings.binding("pipeline", covariates={"ontology": "VERSION"})
def invoke(value: str) -> str:
    return f"ok {value}"
"""
        monkeypatch.chdir(tmp_path)
        bindings_file = tmp_path / "mavai-bindings.py"
        bindings_file.write_text(bindings.replace("VERSION", "abc123"), encoding="utf-8")
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        assert main(["measure", str(contract), "--samples", "50"]) == 0
        # Simulate the next invocation under drifted covariates: fresh
        # bindings import, changed ontology version.
        for key in [k for k in sys.modules if k.startswith("mavai_bindings:")]:
            del sys.modules[key]
        # A different-length value: the source-file change must defeat the
        # bytecode cache's (mtime, size) key within this fast-running test.
        bindings_file.write_text(bindings.replace("VERSION", "def456-drifted"), encoding="utf-8")
        code = main(["test", str(contract), "--tolerate", "84", "--no-verdict-xml"])
        assert code == 2
        output = capsys.readouterr()
        assert "differing: ontology" in output.out + output.err
