"""A failed delivery is stated as one, in the artefact, with its cause.

The incident this closes: four configurations reading `0.000` with every
postcondition skipped, visually identical to a service that answered every
time and was wrong every time. The engine knew the difference — it takes a
separate code path for an undelivered response — and discarded it at
serialisation. These tests hold that distinction all the way to the YAML.
"""

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from baseltest.contract import DeliveryCause, ServiceDeliveryError
from baseltest.declarative import explore
from baseltest.declarative._providers import (
    ENV_ENDPOINT,
    ENV_MODEL,
    build_invoker,
    resolve_provider,
)
from baseltest.declarative._services import LanguageModelParameters

SERVICES = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.2
      deadline-ms: 250
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


def _write_files(tmp_path: Path) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(SERVICES, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(CONTRACT, encoding="utf-8")
    return path


def _artefacts(explorations_dir: Path) -> list[dict[str, Any]]:
    yaml = YAML(typ="safe", pure=True)
    return [
        yaml.load(path.read_text(encoding="utf-8"))
        for path in sorted(explorations_dir.rglob("*.yaml"))
    ]


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


# ── the cause each transport failure states ──────────────────────────────────


def _invoker(monkeypatch: Any, failure: Exception) -> Any:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return build_invoker(
        resolve_provider(None),
        LanguageModelParameters(system_prompt="terse", model="a-model", deadline_ms=1_000),
    )


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid",
        status,
        "err",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b"detail"),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("timed out"), DeliveryCause.CLIENT_DEADLINE),
        (urllib.error.URLError(TimeoutError("timed out")), DeliveryCause.CLIENT_DEADLINE),
        (urllib.error.URLError("connection refused"), DeliveryCause.UNREACHABLE),
        (_http_error(503), DeliveryCause.SERVER_ERROR),
        (_http_error(500), DeliveryCause.SERVER_ERROR),
        # The peer stating a timeout of its own, which is not our deadline
        # elapsing however similar the elapsed seconds look.
        (_http_error(504), DeliveryCause.PEER_TIMEOUT),
    ],
)
def test_each_transport_failure_states_its_cause(
    monkeypatch: Any, failure: Exception, expected: DeliveryCause
) -> None:
    invoke = _invoker(monkeypatch, failure)
    with pytest.raises(ServiceDeliveryError) as raised:
        invoke("hello")
    assert raised.value.cause is expected


def test_a_delivered_body_with_nothing_to_judge_states_its_cause(monkeypatch: Any) -> None:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeResponse(json.dumps({"choices": [{"message": {}}]}).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    invoke = build_invoker(
        resolve_provider(None), LanguageModelParameters(system_prompt="terse", model="a-model")
    )
    with pytest.raises(ServiceDeliveryError) as raised:
        invoke("hello")
    assert raised.value.cause is DeliveryCause.UNUSABLE_RESPONSE


def test_an_author_may_state_no_cause() -> None:
    # ServiceDeliveryError is public: an author raises it from their own
    # binding, where the framework knows nothing about the transport. The
    # cause is then unstated, and unstated is what the artefact says.
    assert ServiceDeliveryError("the vendor SDK gave up").cause is None


# ── what reaches the artefact ────────────────────────────────────────────────


def test_a_run_that_delivers_nothing_emits_delivery_kind_summing_to_failures(
    tmp_path: Path, monkeypatch: Any
) -> None:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    contract = _write_files(tmp_path)
    explore(contract, samples_per_config=4, explorations_dir=tmp_path / "out")

    documents = _artefacts(tmp_path / "out")
    assert documents
    for document in documents:
        statistics = document["statistics"]
        entries = statistics["failureDistribution"]
        assert statistics["successes"] == 0
        assert [entry["kind"] for entry in entries] == ["delivery"]
        assert entries[0]["condition"] == "unreachable"
        # The counting rule is untouched: every undelivered trial is still a
        # failed trial, and the entries still account for all of them.
        assert sum(entry["count"] for entry in entries) == statistics["failures"]


def test_an_ordinary_failing_run_emits_no_delivery_kind(tmp_path: Path, monkeypatch: Any) -> None:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        reply = {"choices": [{"message": {"content": "goodbye"}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    contract = _write_files(tmp_path)
    explore(contract, samples_per_config=4, explorations_dir=tmp_path / "out")

    documents = _artefacts(tmp_path / "out")
    assert documents
    for document in documents:
        entries = document["statistics"]["failureDistribution"]
        assert entries
        assert {entry["kind"] for entry in entries} == {"evaluated"}
        # Every sample was delivered and judged: the failures name the check
        # that did not hold, exactly as they did before the amendment.
        assert all(entry["condition"] != "unreachable" for entry in entries)


def test_a_mixed_run_states_both_kinds(tmp_path: Path, monkeypatch: Any) -> None:
    calls = {"count": 0}

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] % 2:
            raise urllib.error.URLError("connection refused")
        reply = {"choices": [{"message": {"content": "goodbye"}}]}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    contract = _write_files(tmp_path)
    explore(contract, samples_per_config=4, explorations_dir=tmp_path / "out")

    kinds = {
        entry["kind"]
        for document in _artefacts(tmp_path / "out")
        for entry in document["statistics"]["failureDistribution"]
    }
    assert kinds == {"delivery", "evaluated"}


def test_no_endpoint_reaches_the_artefact_as_an_identity(tmp_path: Path, monkeypatch: Any) -> None:
    """The bound the amendment exists to restore.

    The message a reader sees still names the endpoint — that is its job.
    What must not travel is that message as an entry's *identity*, which is
    what a consumer groups and counts on.
    """

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError("nodename nor servname provided")

    monkeypatch.setenv(ENV_ENDPOINT, "https://secret-gateway.internal/v1/chat/completions")
    monkeypatch.setenv(ENV_MODEL, "env-default-model")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    contract = _write_files(tmp_path)
    explore(contract, samples_per_config=2, explorations_dir=tmp_path / "out")

    for document in _artefacts(tmp_path / "out"):
        for entry in document["statistics"]["failureDistribution"]:
            assert "secret-gateway.internal" not in entry["condition"]
            assert entry["condition"] in {cause.value for cause in DeliveryCause}
