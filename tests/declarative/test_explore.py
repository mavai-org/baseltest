"""The explore verb: the configuration grid, its refusals, and the fingerprint law."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import binding, explore, run
from baseltest.declarative._cli import main
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL
from baseltest.declarative._registry import clear_registries
from baseltest.declarative._services import parse_services

SERVICES = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.2
    explorations:
      - temperature: 0.0
      - temperature: 0.7
      - model: other-model
        temperature: 0.7
"""

CONTRACT = """
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs: ["Where is my order?", "Do you ship abroad?"]
criteria:
  - name: says-hello
    threshold: 0.5
    contains: "hello"
"""


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


@pytest.fixture()
def llm_environment(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A stubbed OpenAI-compatible endpoint capturing request payloads."""
    captured: list[dict[str, Any]] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request: Any) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        captured.append(payload)
        reply = {"choices": [{"message": {"content": f"hello from {payload['model']}"}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


def write_files(tmp_path: Path, contract: str = CONTRACT, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


class TestGridParsing:
    def test_grid_is_baseline_plus_entries(self) -> None:
        definition = parse_services(SERVICES)["support-agent"]
        assert len(definition.grid) == 4
        assert definition.grid[0] is definition.configuration
        assert definition.explorations[0].temperature == 0.0
        assert definition.explorations[0].model == "small-model"  # baseline kept
        assert definition.explorations[2].model == "other-model"
        assert definition.explorations[2].temperature == 0.7
        assert definition.explorations[2].system_prompt == "You are a support agent."

    def test_swept_keys_are_the_replaced_ones_in_canonical_order(self) -> None:
        definition = parse_services(SERVICES)["support-agent"]
        assert definition.swept_keys == ("model", "temperature")

    def test_file_without_explorations_is_unchanged(self) -> None:
        text = SERVICES[: SERVICES.index("    explorations:")]
        definition = parse_services(text)["support-agent"]
        assert definition.explorations == ()
        assert definition.swept_keys == ()

    def test_entry_restating_the_baseline_is_refused(self) -> None:
        text = SERVICES + "      - temperature: 0.2\n"
        with pytest.raises(ContractConfigurationError, match="baseline `configuration:`"):
            parse_services(text)

    def test_two_entries_resolving_to_one_point_are_refused_naming_both(self) -> None:
        text = SERVICES + "      - model: other-model\n        temperature: 0.7\n"
        with pytest.raises(
            ContractConfigurationError,
            match=r"entry 4 resolves to the same configuration as exploration entry 3",
        ):
            parse_services(text)

    def test_spelling_does_not_matter_only_the_resolved_point(self) -> None:
        # Restates the baseline model explicitly: same resolved point as entry 2.
        text = SERVICES + "      - model: small-model\n        temperature: 0.7\n"
        with pytest.raises(ContractConfigurationError, match="exploration entry 2"):
            parse_services(text)

    def test_unknown_key_in_an_entry_is_refused(self) -> None:
        text = SERVICES + "      - label: warm\n        temperature: 0.9\n"
        with pytest.raises(ContractConfigurationError, match="unknown key `label:`"):
            parse_services(text)

    def test_null_replacement_values_are_refused(self) -> None:
        text = SERVICES + "      - temperature:\n"
        with pytest.raises(ContractConfigurationError, match="omit a key"):
            parse_services(text)

    def test_empty_explorations_section_is_refused(self) -> None:
        text = SERVICES.replace(
            "    explorations:\n      - temperature: 0.0\n      - temperature: 0.7\n"
            "      - model: other-model\n        temperature: 0.7\n",
            "    explorations: []\n",
        )
        with pytest.raises(ContractConfigurationError, match="non-empty list"):
            parse_services(text)


class TestExploreRuns:
    def test_one_artefact_per_configuration_baseline_included(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        explored = explore(
            write_files(tmp_path), samples_per_config=3, explorations_dir=tmp_path / "x", emit=False
        )
        assert len(explored) == 4
        files = sorted(p.name for p in (tmp_path / "x" / "support-agent-tuning").glob("*.yaml"))
        assert files == [
            "model-other-model_temperature-0.7.yaml",
            "model-small-model_temperature-0.0.yaml",
            "model-small-model_temperature-0.2.yaml",
            "model-small-model_temperature-0.7.yaml",
        ]
        # 4 configurations x 3 samples each, every one a real invocation
        assert len(llm_environment) == 12
        assert {p["temperature"] for p in llm_environment} == {0.0, 0.2, 0.7}

    def test_artefacts_carry_projections_and_gated_latency(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        import io as _io

        from ruamel.yaml import YAML

        explored = explore(
            write_files(tmp_path), samples_per_config=3, explorations_dir=tmp_path / "x", emit=False
        )
        yaml = YAML(typ="safe", pure=True)
        data = yaml.load(_io.StringIO(explored[0].path.read_text(encoding="utf-8")))
        projection = data["resultProjection"]
        assert len(projection) == 3  # one entry per sample
        first = projection["sample[0]"]
        assert first["inputIndex"] == 0
        assert first["content"].startswith("hello from")  # the actual response, verbatim
        assert set(first["postconditions"].values()) <= {"passed", "failed", "skipped"}
        assert isinstance(first["executionTimeMs"], int)
        latency = data["latency"]
        assert latency["basis"] == "passing-samples"
        assert "p50Ms" in latency and "p99Ms" not in latency  # gated at n=3
        # anchors mark every sample boundary for diff alignment
        text = explored[0].path.read_text(encoding="utf-8")
        assert text.count("anchor:") == 3

    def test_console_names_the_most_common_failure(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        contract = CONTRACT.replace('contains: "hello"', 'contains: "impossible"')
        explore(
            write_files(tmp_path, contract), samples_per_config=2, explorations_dir=tmp_path / "x"
        )
        out = capsys.readouterr().out
        assert "most common failure: 2× " in out

    def test_artefacts_are_descriptive_only(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        explored = explore(
            write_files(tmp_path), samples_per_config=3, explorations_dir=tmp_path / "x", emit=False
        )
        for entry in explored:
            text = entry.path.read_text(encoding="utf-8")
            assert '"punit-spec-1"' in text
            for word in ("verdict", "threshold", "confidence", "bound"):
                assert word not in text

    def test_console_output_has_no_verdict_vocabulary(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        assert (
            main(["explore", str(write_files(tmp_path)), "--explorations-dir", str(tmp_path / "x")])
            == 0
        )
        out = capsys.readouterr().out
        assert "explored 4 configurations" in out
        assert "renders no verdict" in out
        for word in ("PASS", "FAIL", "verdict record", "threshold"):
            assert word not in out

    def test_a_single_sample_is_not_complained_about(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        explored = explore(
            write_files(tmp_path), samples_per_config=1, explorations_dir=tmp_path / "x"
        )
        assert all(e.result.plan.samples == 1 for e in explored)

    def test_thresholds_are_not_consulted(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        # A bar 3 samples could never support: a test would be refused,
        # an exploration proceeds — feasibility protects verdicts only.
        contract = CONTRACT.replace("threshold: 0.5", "threshold: 0.999")
        explored = explore(
            write_files(tmp_path, contract),
            samples_per_config=3,
            explorations_dir=tmp_path / "x",
            emit=False,
        )
        assert all(r.verdict is None for e in explored for r in e.result.criterion_results)

    def test_no_flag_runs_the_small_default_per_configuration(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        explored = explore(write_files(tmp_path), explorations_dir=tmp_path / "x")
        assert all(e.result.plan.samples == 5 for e in explored)
        assert (
            "n = 5 per configuration (default; use --samples-per-config to size the run)"
            in capsys.readouterr().out
        )

    def test_withdrawn_file_key_is_refused_naming_the_flag(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        contract = CONTRACT.replace("inputs:", "samples-per-config: 3\ninputs:")
        with pytest.raises(ContractConfigurationError, match="--samples-per-config"):
            explore(write_files(tmp_path, contract), emit=False)

    def test_code_registered_binding_is_refused_with_a_pointer(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        @binding("support-agent")
        def invoke(value: str) -> str:
            return "hello"

        contract = write_files(
            tmp_path,
            services="format: mavai-services/1\nservices:\n"
            "  unrelated:\n    type: language-model\n"
            '    configuration:\n      system-prompt: "x"\n',
        )
        with pytest.raises(ContractConfigurationError, match="declared service"):
            explore(contract, emit=False)

    def test_cli_samples_per_config_flag_sizes_the_run(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        assert (
            main(
                [
                    "explore",
                    str(write_files(tmp_path)),
                    "--samples-per-config",
                    "2",
                    "--explorations-dir",
                    str(tmp_path / "x"),
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "n = 2 per configuration (set via --samples-per-config)" in out
        assert len(llm_environment) == 8  # 4 configurations x 2 samples

    def test_default_artefact_root(
        self,
        tmp_path: Path,
        llm_environment: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["explore", str(write_files(tmp_path))]) == 0
        root = tmp_path / "_baseltest" / "explorations" / "support-agent-tuning"
        assert len(list(root.glob("*.yaml"))) == 4


class TestMixedProviderGrids:
    SCHEMA_SERVICES = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent. Reply with only a JSON object."
      model: small-model
      temperature: 0.2
      response-schema:
        type: object
        properties: { answer: { type: string } }
    explorations:
      - provider: apertus
        model: swiss-model
"""

    def test_schema_less_provider_is_warned_and_invoked_not_refused(
        self,
        tmp_path: Path,
        llm_environment: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: Any,
    ) -> None:
        monkeypatch.setenv("PUBLICAI_API_KEY", "test-key")
        explored = explore(
            write_files(tmp_path, services=self.SCHEMA_SERVICES),
            samples_per_config=1,
            explorations_dir=tmp_path / "x",
        )
        assert len(explored) == 2  # the run proceeded across both providers
        out = capsys.readouterr().out
        assert "no structured-output support" in out
        assert "system prompt" in out
        # The baseline (generic provider) request carries the schema; the
        # apertus request does not — dropped with the warning, never silently.
        with_schema = [p for p in llm_environment if "response_format" in p]
        without_schema = [p for p in llm_environment if "response_format" not in p]
        assert len(with_schema) == 1 and len(without_schema) == 1

    def test_measure_still_refuses_a_schema_the_provider_cannot_honour(
        self,
        tmp_path: Path,
        llm_environment: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Population identity is load-bearing for measure/test: no degradation.
        monkeypatch.setenv("PUBLICAI_API_KEY", "test-key")
        services = self.SCHEMA_SERVICES.replace(
            "      temperature: 0.2\n", "      temperature: 0.2\n      provider: apertus\n"
        )
        with pytest.raises(ContractConfigurationError, match="cannot be honoured"):
            run(
                write_files(tmp_path, services=services),
                mode="measure",
                samples=5,
                emit=False,
            )


class TestOtherVerbsIgnoreTheGrid:
    def test_measure_and_test_consume_the_baseline_only(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        contract = write_files(tmp_path)
        run(contract, mode="measure", samples=40, baseline_dir=tmp_path / "b", emit=False)
        assert {p["temperature"] for p in llm_environment} == {0.2}  # baseline only

    def test_behaviour_is_identical_with_and_without_the_section(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        with_grid = write_files(tmp_path)
        result_a = run(
            with_grid, mode="measure", samples=40, baseline_dir=tmp_path / "a", emit=False
        )
        without = SERVICES[: SERVICES.index("    explorations:")]
        (tmp_path / "mavai-services.yaml").write_text(without, encoding="utf-8")
        result_b = run(
            with_grid, mode="measure", samples=40, baseline_dir=tmp_path / "b", emit=False
        )
        text_a = next((tmp_path / "a").glob("*.yaml")).read_text(encoding="utf-8")
        text_b = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")

        # Identical artefacts modulo the timestamp line: the grid leaves no trace.
        def strip(text: str) -> list[str]:
            return [line for line in text.splitlines() if not line.startswith("generatedAt")]

        assert strip(text_a) == strip(text_b)
        assert result_a.plan.samples == result_b.plan.samples


EMPIRICAL_CONTRACT = """
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs: ["Where is my order?", "Do you ship abroad?"]
criteria:
  - name: says-hello
    contains: "hello"
"""


class TestFingerprintLaw:
    """The configuration fingerprint is a function of the resolved covariates only."""

    def _measure_then_test(self, tmp_path: Path, services_after: str) -> Any:
        contract = write_files(tmp_path, EMPIRICAL_CONTRACT)
        run(contract, mode="measure", samples=40, baseline_dir=tmp_path / "b", emit=False)
        (tmp_path / "mavai-services.yaml").write_text(services_after, encoding="utf-8")
        return run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False)

    def test_reordering_exploration_entries_leaves_the_baseline_matching(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        reordered = SERVICES.replace(
            "      - temperature: 0.0\n      - temperature: 0.7\n",
            "      - temperature: 0.7\n      - temperature: 0.0\n",
        )
        result = self._measure_then_test(tmp_path, reordered)
        judged = result.criterion_results[0]
        assert judged.verdict is not None  # empirical bar found and applied
        assert judged.criterion.provenance.origin == "empirical"

    def test_removing_the_section_entirely_leaves_the_baseline_matching(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]]
    ) -> None:
        without = SERVICES[: SERVICES.index("    explorations:")]
        result = self._measure_then_test(tmp_path, without)
        assert result.criterion_results[0].verdict is not None

    def test_folding_a_sweep_winner_into_the_baseline_trips_the_ratchet(
        self, tmp_path: Path, llm_environment: list[dict[str, Any]], capsys: Any
    ) -> None:
        promoted = SERVICES.replace("temperature: 0.2", "temperature: 0.7").replace(
            "      - temperature: 0.7\n", "      - temperature: 0.2\n"
        )
        contract = write_files(tmp_path, EMPIRICAL_CONTRACT)
        run(contract, mode="measure", samples=40, baseline_dir=tmp_path / "b", emit=False)
        (tmp_path / "mavai-services.yaml").write_text(promoted, encoding="utf-8")
        # The recorded baseline no longer matches the resolved covariates:
        # the test refuses until a fresh measure run is made, naming the drift.
        with pytest.raises(ContractConfigurationError, match="temperature") as refusal:
            run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False)
        assert "different configuration" in str(refusal.value)

    def test_environment_defaulted_covariates_are_fingerprinted_as_resolved(
        self,
        tmp_path: Path,
        llm_environment: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: Any,
    ) -> None:
        no_model = SERVICES.replace("      model: small-model\n", "").replace(
            "      - model: other-model\n        temperature: 0.7\n", ""
        )
        contract = write_files(tmp_path, EMPIRICAL_CONTRACT, services=no_model)
        run(contract, mode="measure", samples=40, baseline_dir=tmp_path / "b", emit=False)
        monkeypatch.setenv(ENV_MODEL, "a-different-default")
        # Same file, different environment default: a different population,
        # and the fingerprint says so.
        with pytest.raises(ContractConfigurationError, match="different configuration"):
            run(contract, mode="test", baseline_dir=tmp_path / "b", emit=False)
