"""Binding-declared covariates: registration, recording, and drift refusal."""

from pathlib import Path

import pytest

from baseltest.declarative import binding, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._registry import (
    binding_covariates,
    clear_registries,
)
from baseltest.engine import Verdict


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


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


def register_pipeline(covariates: dict[str, str] | None) -> None:
    @binding("pipeline", covariates=covariates)
    def invoke(value: str) -> str:
        return f"ok {value}"


class TestRegistration:
    def test_declared_covariates_are_resolvable(self) -> None:
        register_pipeline({"ontology": "abc123", "judge": "v2"})
        assert binding_covariates("pipeline") == {"ontology": "abc123", "judge": "v2"}

    def test_omitted_covariates_resolve_empty(self) -> None:
        register_pipeline(None)
        assert binding_covariates("pipeline") == {}

    def test_reserved_key_refused_naming_the_key(self) -> None:
        for reserved in ("binding", "runMode", "serviceType", "taskFile", "taskFormat"):
            with pytest.raises(ContractConfigurationError, match=reserved):
                binding("svc", covariates={reserved: "x"})

    def test_non_string_value_refused_with_the_type_named(self) -> None:
        with pytest.raises(ContractConfigurationError, match="int"):
            binding("svc", covariates={"catalogue-size": 40})  # type: ignore[dict-item]

    def test_empty_key_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="non-empty"):
            binding("svc", covariates={"": "x"})

    def test_covariates_of_an_unregistered_binding_are_refused(self) -> None:
        with pytest.raises(ContractConfigurationError, match="@binding"):
            binding_covariates("ghost")


class TestBaselineRecording:
    def test_measure_persists_covariates_in_provenance(self, tmp_path: Path) -> None:
        register_pipeline({"ontology": "abc123"})
        run(
            write_contract(tmp_path, EMPIRICAL_CONTRACT),
            mode="measure",
            samples=50,
            baseline_dir=tmp_path / "baselines",
            emit=False,
        )
        (artefact,) = (tmp_path / "baselines").glob("*.yaml")
        content = artefact.read_text(encoding="utf-8")
        assert '"ontology": "abc123"' in content

    def test_test_resolves_the_baseline_under_matching_covariates(self, tmp_path: Path) -> None:
        register_pipeline({"ontology": "abc123"})
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(contract, mode="measure", samples=200, baseline_dir=tmp_path / "b", emit=False)
        result = run(contract, mode="test", samples=200, baseline_dir=tmp_path / "b", emit=False)
        assert result.composite is Verdict.PASS
        assert result.criterion_results[0].criterion.provenance.origin == "empirical"


class TestDriftRefusal:
    def test_drifted_covariate_refuses_naming_the_key(self, tmp_path: Path) -> None:
        register_pipeline({"ontology": "abc123"})
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(contract, mode="measure", samples=50, baseline_dir=tmp_path / "b", emit=False)
        clear_registries()
        register_pipeline({"ontology": "def456"})
        with pytest.raises(ContractConfigurationError) as refusal:
            run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False)
        assert "different configuration" in str(refusal.value)
        assert "ontology" in str(refusal.value)

    def test_added_covariate_refuses_naming_the_key(self, tmp_path: Path) -> None:
        register_pipeline(None)
        contract = write_contract(tmp_path, EMPIRICAL_CONTRACT)
        run(contract, mode="measure", samples=50, baseline_dir=tmp_path / "b", emit=False)
        clear_registries()
        register_pipeline({"judge": "v2"})
        with pytest.raises(ContractConfigurationError, match="judge"):
            run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False)
