"""Emitter conformance: optimization artefacts validate against the family interchange schema.

The pinned copy of the published ``mavai-optimize-1`` JSON schema lives under
``tests/conformance/interchange/``. A small real optimize run drives the
engine, and the emitted YAML document must validate against that schema —
plus the semantic obligations the schema cannot express: the convergence
block's cross-consistency with the iteration it names (the schema-specific
binding obligation), the stated-value-or-absent percentile gate per
iteration, and vector/population-indicator consistency, referenced through
the engine's own gating table.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from baseltest.declarative import optimize
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL
from baseltest.engine import minimum_contributing_samples

_SCHEMA_PATH = Path(__file__).parent.parent / "conformance" / "interchange"
_SCHEMA = json.loads((_SCHEMA_PATH / "mavai-optimize-1.schema.json").read_text(encoding="utf-8"))

SERVICES = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.2
    optimizations:
      - id: temperature-linear
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.3}
        initial: {temperature: 0.0}
        max-iterations: 6
"""

CONTRACT = """
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs: ["Where is my order?", "Do you ship abroad?"]
criteria:
  - name: says-hello
    contains: "hello"
"""


@pytest.fixture()
def alternating_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stubbed endpoint whose replies alternate matching and non-matching.

    With an even per-iteration sample count, every iteration observes
    exactly half passing samples — enough to exercise the failure
    distribution and a populated latency block in every iteration.
    """
    calls = {"count": 0}

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request: Any, **_: Any) -> FakeResponse:
        calls["count"] += 1
        content = "hello there" if calls["count"] % 2 else "goodbye"
        reply = {"choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


REFINING_SERVICES = SERVICES.replace(
    """      - id: temperature-linear
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.3}
        initial: {temperature: 0.0}
        max-iterations: 6
""",
    """      - id: temperature-refining
        stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.5, min-step: 0.25}
        initial: {temperature: 0.0}
        max-iterations: 20
""",
)


def write_files(tmp_path: Path, contract: str = CONTRACT, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


def load_artefact(path: Path) -> dict[str, Any]:
    data = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def assert_semantic_obligations(document: dict[str, Any]) -> None:
    """The obligations the schema cannot express, per emitted document."""
    assert isinstance(document["generatedAt"], str)
    # The schema-specific binding obligation: the convergence block is
    # internally consistent with the iterations entry it names.
    convergence = document["convergence"]
    assert convergence["totalIterations"] == len(document["iterations"])
    best = document["iterations"][convergence["bestIteration"]]
    assert convergence["bestScore"] == best["score"]
    assert convergence["bestFactors"] == best["factors"]
    for entry in document["iterations"]:
        latency = entry.get("latency")
        if latency is None:
            continue
        vector = latency["sortedPassingLatenciesMs"]
        assert vector == sorted(vector)
        assert latency["contributingSamples"] == len(vector)
        assert latency["contributingSamples"] <= latency["totalSamples"]
        # Stated value-or-absent: each percentile appears iff the
        # contributing count clears the engine's own minimum-sample gate.
        for label in ("p50", "p90", "p95", "p99"):
            cleared = latency["contributingSamples"] >= minimum_contributing_samples(label)
            assert (f"{label}Ms" in latency) == cleared


def assert_selection_obligations(document: dict[str, Any]) -> None:
    """``convergence.selection`` restates evidence pooled from the iterations.

    Each standing's successes and trials are the sums over every iteration
    that ran its factor values, and the selected standing is a finalist.
    """
    selection = document["convergence"]["selection"]
    standings = [selection, *selection["finalists"]]
    for standing in standings:
        pooled = [
            entry
            for entry in document["iterations"]
            if all(entry["factors"][key] == value for key, value in standing["factors"].items())
        ]
        assert standing["successes"] == sum(e["statistics"]["successes"] for e in pooled)
        assert standing["trials"] == sum(e["execution"]["samplesExecuted"] for e in pooled)
        assert standing["rate"] == round(standing["successes"] / standing["trials"], 6)
        assert standing["intervalLow"] <= standing["rate"] <= standing["intervalHigh"]
    assert selection["factors"] in [finalist["factors"] for finalist in selection["finalists"]]


class TestInterchangeConformance:
    def test_a_refining_grid_artefact_carries_its_selection_and_validates(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        outcomes = optimize(
            write_files(tmp_path, services=REFINING_SERVICES),
            samples_per_iteration=4,
            optimizations_dir=tmp_path / "o",
            emit=False,
        )
        document = load_artefact(outcomes[0].path)
        Draft202012Validator(_SCHEMA).validate(document)
        assert_semantic_obligations(document)
        assert_selection_obligations(document)
        selection = document["convergence"]["selection"]
        assert selection["stepper"] == "refining-grid"
        assert selection["confidence"] == 0.95
        assert selection["stoppingReason"] in ("min-step", "no-plausible-challenger")
        # The selection is the artefact's, not mutator provenance.
        assert "selectedValue" not in document["stepper"]

    def test_a_non_selecting_stepper_leaves_selection_absent(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        outcomes = optimize(
            write_files(tmp_path),
            samples_per_iteration=4,
            optimizations_dir=tmp_path / "o",
            emit=False,
        )
        document = load_artefact(outcomes[0].path)
        Draft202012Validator(_SCHEMA).validate(document)
        assert "selection" not in document["convergence"]

    def test_a_mixed_run_artefact_validates_against_the_published_schema(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        outcomes = optimize(
            write_files(tmp_path),
            samples_per_iteration=12,
            optimizations_dir=tmp_path / "o",
            emit=False,
        )
        document = load_artefact(outcomes[0].path)
        Draft202012Validator(_SCHEMA).validate(document)
        assert_semantic_obligations(document)
        assert len(document["iterations"]) == 4  # 0.0, 0.1, 0.2, 0.3, then stop
        for entry in document["iterations"]:
            # Half of 12 samples passed: the failure distribution is present,
            # and 6 contributing samples state p50 but no deeper percentile.
            assert entry["statistics"]["failureDistribution"]
            assert "p50Ms" in entry["latency"]
            assert "p95Ms" not in entry["latency"]

    def test_a_run_with_no_passing_samples_omits_latency_and_validates(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        contract = CONTRACT.replace('contains: "hello"', 'contains: "impossible"')
        outcomes = optimize(
            write_files(tmp_path, contract),
            samples_per_iteration=4,
            optimizations_dir=tmp_path / "o",
            emit=False,
        )
        document = load_artefact(outcomes[0].path)
        Draft202012Validator(_SCHEMA).validate(document)
        assert_semantic_obligations(document)
        for entry in document["iterations"]:
            assert "latency" not in entry
            assert entry["statistics"]["failureDistribution"]
