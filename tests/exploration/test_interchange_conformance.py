"""Emitter conformance: exploration artefacts validate against the family interchange schema.

The pinned copy of the published ``mavai-explore-1`` JSON schema lives under
``tests/conformance/interchange/``. A small real exploration runs through the
engine, and every emitted YAML document must validate against that schema —
plus the semantic obligations the schema cannot express (vector ordering,
population-indicator consistency, and the stated-value-or-absent percentile
gate, referenced through the engine's own gating table).
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from baseltest.declarative import explore
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL
from baseltest.declarative._registry import clear_registries
from baseltest.engine import minimum_contributing_samples

_SCHEMA_PATH = Path(__file__).parent.parent / "conformance" / "interchange"
_SCHEMA = json.loads((_SCHEMA_PATH / "mavai-explore-1.schema.json").read_text(encoding="utf-8"))

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
def alternating_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stubbed endpoint whose replies alternate matching and non-matching.

    With an even per-configuration sample count, every configuration
    observes exactly half passing samples — enough to exercise both the
    failure distribution and a populated latency block in one artefact.
    """
    calls = {"count": 0}

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request: Any) -> FakeResponse:
        calls["count"] += 1
        content = "hello there" if calls["count"] % 2 else "goodbye"
        reply = {"choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def write_files(tmp_path: Path, contract: str = CONTRACT) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(SERVICES, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


def load_artefacts(explorations_dir: Path) -> list[dict[str, Any]]:
    yaml = YAML(typ="safe", pure=True)
    documents = []
    for path in sorted(explorations_dir.rglob("*.yaml")):
        data = yaml.load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        documents.append(data)
    return documents


def assert_semantic_obligations(document: dict[str, Any]) -> None:
    """The obligations the schema cannot express, per emitted document."""
    # The quoted timestamp must survive YAML loading as a string — a
    # datetime object would mean the emitter stopped quoting it.
    assert isinstance(document["generatedAt"], str)
    latency = document.get("latency")
    if latency is None:
        return
    vector = latency["sortedPassingLatenciesMs"]
    assert vector == sorted(vector)
    assert latency["contributingSamples"] == len(vector)
    assert latency["contributingSamples"] <= latency["totalSamples"]
    # Stated value-or-absent: each percentile appears iff the contributing
    # count clears the engine's own minimum-sample gate.
    for label in ("p50", "p90", "p95", "p99"):
        cleared = latency["contributingSamples"] >= minimum_contributing_samples(label)
        assert (f"{label}Ms" in latency) == cleared


def _every_mapping_key(node: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_every_mapping_key(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_every_mapping_key(item))
    return keys


class TestInterchangeConformance:
    def test_mixed_run_artefacts_validate_against_the_published_schema(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        explore(
            write_files(tmp_path),
            samples_per_config=12,
            explorations_dir=tmp_path / "x",
            emit=False,
        )
        documents = load_artefacts(tmp_path / "x")
        assert len(documents) == 3  # baseline plus two explorations
        validator = Draft202012Validator(_SCHEMA)
        for document in documents:
            validator.validate(document)
            assert_semantic_obligations(document)
            # Half of 12 samples passed: the failure distribution is
            # present, and 6 contributing samples state p50 but no
            # deeper-tail percentile.
            assert document["statistics"]["failureDistribution"]
            assert "p50Ms" in document["latency"]
            assert "p95Ms" not in document["latency"]

    def test_no_passing_samples_omits_the_latency_block_and_validates(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        contract = CONTRACT.replace('contains: "hello"', 'contains: "impossible"')
        explore(
            write_files(tmp_path, contract),
            samples_per_config=4,
            explorations_dir=tmp_path / "x",
            emit=False,
        )
        documents = load_artefacts(tmp_path / "x")
        validator = Draft202012Validator(_SCHEMA)
        for document in documents:
            validator.validate(document)
            assert_semantic_obligations(document)
            assert "latency" not in document
            assert document["statistics"]["failureDistribution"]

    def test_a_run_driven_by_an_over_long_input_emits_valid_bounded_artefacts(
        self, tmp_path: Path, alternating_endpoint: None
    ) -> None:
        """Artefact key discipline: input text never becomes key content.

        A per-input expectation used to embed the driving input's full
        text in check identities, so a real-world input past YAML's
        1,024-character implicit-key limit made the emitted artefact
        unparseable by spec-strict parsers. Identity is structural now:
        the input's position, with the text quoted only as a bounded
        excerpt value.
        """
        long_input = "Where is my order? The details follow, at length. " * 30
        assert len(long_input) > 1024
        contract = f"""
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs:
  - input: {json.dumps(long_input)}
    expected: {{ contains: "impossible" }}
criteria:
  - name: says-hello
    threshold: 0.5
    contains: "hello"
"""
        explore(
            write_files(tmp_path, contract),
            samples_per_config=4,
            explorations_dir=tmp_path / "x",
            emit=False,
        )
        paths = sorted((tmp_path / "x").rglob("*.yaml"))
        assert paths
        validator = Draft202012Validator(_SCHEMA)
        yaml = YAML(typ="safe", pure=True)
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            # The full input appears nowhere — not in keys, not in values;
            # only a bounded excerpt may quote it.
            assert long_input not in raw
            document = yaml.load(raw)  # spec-strict parse is the point
            validator.validate(document)
            for key in _every_mapping_key(document):
                assert len(key) <= 256
            distribution = document["statistics"]["failureDistribution"]
            assert (
                sum(entry["count"] for entry in distribution)
                == (document["statistics"]["failures"])
            )
            per_input = [entry for entry in distribution if "inputIndex" in entry]
            assert per_input
            for entry in per_input:
                assert entry["inputIndex"] == 0
                assert len(entry.get("inputExcerpt", "")) <= 256
