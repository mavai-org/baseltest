"""User-registered service types: configuration, grids, provenance, refusals."""

from collections.abc import Callable
from pathlib import Path

import pytest

from baseltest.declarative import Registry, explore, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._services import parse_services
from baseltest.engine import Verdict

SERVICES = """
format: mavai-services/1
services:
  cheerful-teller:
    type: fortune-teller
    configuration:
      mood: cheerful
      emphasis: 2
    explorations:
      - mood: gloomy
"""

CONTRACT = """
format: mavai-contract/1
contract: teller-stays-on-mood
service: cheerful-teller
criteria:
  - name: on-mood
    threshold: 0.5
    contains: "cheerful"
  - name: observed
    contains: "!"
inputs: ["Alice", "Bob"]
"""


def register_teller(registry: Registry, covariates: dict[str, str] | None = None) -> None:
    @registry.binding_factory("fortune-teller", covariates=covariates)
    def fortune_teller(mood: str = "plain", emphasis: int = 1) -> Callable[[str], str]:
        def tell(name: str) -> str:
            return f"{mood} fortune for {name}" + "!" * emphasis

        return tell


def write_files(tmp_path: Path, services: str = SERVICES, contract: str = CONTRACT) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


class TestConfiguredRuns:
    def test_test_runs_the_baseline_configuration(self, tmp_path: Path) -> None:
        registry = Registry()
        register_teller(registry)
        result = run(write_files(tmp_path), emit=False, registry=registry)
        assert result.composite is Verdict.PASS

    def test_measure_provenance_carries_type_configuration_and_covariates(
        self, tmp_path: Path
    ) -> None:
        registry = Registry()
        register_teller(registry, covariates={"catalogue": "v1"})
        run(
            write_files(tmp_path),
            mode="measure",
            samples=20,
            baseline_dir=tmp_path / "b",
            emit=False,
            registry=registry,
        )
        (artefact,) = (tmp_path / "b").glob("*.yaml")
        content = artefact.read_text(encoding="utf-8")
        assert '"serviceType": "fortune-teller"' in content
        assert '"mood": "cheerful"' in content
        assert '"emphasis": "2"' in content
        assert '"catalogue": "v1"' in content

    def test_configuration_drift_is_refused_naming_the_key(self, tmp_path: Path) -> None:
        registry = Registry()
        register_teller(registry)
        empirical_only = CONTRACT.replace(
            '  - name: on-mood\n    threshold: 0.5\n    contains: "cheerful"\n', ""
        )
        contract = write_files(tmp_path, contract=empirical_only)
        run(
            contract,
            mode="measure",
            samples=20,
            baseline_dir=tmp_path / "b",
            emit=False,
            registry=registry,
        )
        write_files(
            tmp_path,
            services=SERVICES.replace("mood: cheerful", "mood: solemn"),
            contract=empirical_only,
        )
        with pytest.raises(ContractConfigurationError) as refusal:
            run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False, registry=registry)
        assert "mood" in str(refusal.value)


class TestExploration:
    def test_explore_runs_every_grid_point_with_factor_naming(self, tmp_path: Path) -> None:
        registry = Registry()
        register_teller(registry)
        explored = explore(
            write_files(tmp_path),
            samples_per_config=2,
            explorations_dir=tmp_path / "x",
            emit=False,
            registry=registry,
        )
        assert [e.factors for e in explored] == [{"mood": "cheerful"}, {"mood": "gloomy"}]
        assert sorted(p.name for p in (tmp_path / "x" / "teller-stays-on-mood").iterdir()) == [
            "mood-cheerful.yaml",
            "mood-gloomy.yaml",
        ]

    def test_swept_keys_follow_baseline_declaration_order(self) -> None:
        registry = Registry()
        register_teller(registry)
        definitions = parse_services(
            SERVICES.replace("- mood: gloomy", "- {emphasis: 3, mood: gloomy}"), registry
        )
        assert definitions["cheerful-teller"].swept_keys == ("mood", "emphasis")


class TestConfigurationRefusals:
    def test_unknown_key_lists_accepted_keys_and_signature(self) -> None:
        registry = Registry()
        register_teller(registry)
        with pytest.raises(ContractConfigurationError) as refusal:
            parse_services(SERVICES.replace("mood: cheerful", "moods: cheerful"), registry)
        message = str(refusal.value)
        assert "unknown key `moods:`" in message
        assert "accepts: emphasis, mood" in message
        assert "fortune-teller(mood: str = 'plain', emphasis: int = 1)" in message

    def test_missing_required_key_names_it_with_the_signature(self) -> None:
        registry = Registry()

        @registry.binding_factory("strict-teller")
        def strict_teller(mood: str) -> Callable[[str], str]:
            return lambda name: f"{mood} {name}"

        with pytest.raises(ContractConfigurationError) as refusal:
            parse_services(
                SERVICES.replace("type: fortune-teller", "type: strict-teller"), registry
            )
        message = str(refusal.value)
        assert "unknown key `emphasis:`" in message or "missing `mood:`" in message

    def test_annotated_type_mismatch_is_refused(self) -> None:
        registry = Registry()
        register_teller(registry)
        with pytest.raises(ContractConfigurationError, match="expects int, got str"):
            parse_services(SERVICES.replace("emphasis: 2", 'emphasis: "two"'), registry)

    def test_non_scalar_value_is_refused(self) -> None:
        registry = Registry()
        register_teller(registry)
        with pytest.raises(ContractConfigurationError, match="scalar"):
            parse_services(SERVICES.replace("mood: cheerful", "mood: {a: 1}"), registry)

    def test_covariate_and_configuration_key_collision_is_refused(self) -> None:
        registry = Registry()

        @registry.binding_factory("clashing", covariates={"mood": "fixed"})
        def clashing(mood: str = "plain") -> Callable[[str], str]:
            return lambda name: name

        with pytest.raises(ContractConfigurationError, match="one identity key, one feed"):
            parse_services(SERVICES.replace("type: fortune-teller", "type: clashing"), registry)

    def test_reserved_provenance_key_in_configuration_is_refused(self) -> None:
        registry = Registry()

        @registry.binding_factory("reserved-keys")
        def reserved_keys(**configuration: str) -> Callable[[str], str]:
            return lambda name: name

        with pytest.raises(ContractConfigurationError, match="framework"):
            parse_services(
                SERVICES.replace("type: fortune-teller", "type: reserved-keys").replace(
                    "mood: cheerful", "binding: x"
                ),
                registry,
            )

    def test_unknown_type_lists_the_registered_types(self) -> None:
        registry = Registry()
        register_teller(registry)
        with pytest.raises(ContractConfigurationError) as refusal:
            parse_services(
                SERVICES.replace("type: fortune-teller", "type: fortune-tellers"), registry
            )
        message = str(refusal.value)
        assert "registered types: language-model, fortune-teller" in message
        assert "did you mean 'fortune-teller'?" in message

    def test_factory_returning_a_non_callable_is_refused(self, tmp_path: Path) -> None:
        registry = Registry()

        @registry.binding_factory("fortune-teller")
        def fortune_teller(mood: str = "plain", emphasis: int = 1) -> str:
            return mood

        with pytest.raises(ContractConfigurationError, match="not the per-sample callable"):
            run(write_files(tmp_path), emit=False, registry=registry)

    def test_positional_only_factory_parameters_are_refused_at_registration(self) -> None:
        registry = Registry()
        with pytest.raises(ContractConfigurationError, match="keyword-bindable"):

            @registry.binding_factory("positional")
            def positional(mood: str, /) -> Callable[[str], str]:
                return lambda name: name
