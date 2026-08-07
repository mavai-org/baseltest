"""The deadline is declared, finite, stated, and enforced at the socket.

`deadline-ms:` is admitted as a language-model configuration key: validated at
load time, defaulted when unstated, recorded in identity so a changed deadline
drifts a baseline, and — the point of the whole exercise — actually passed to
the transport, so a peer that accepts a request and then says nothing ends the
sample instead of the run.
"""

import socket
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from baseltest.contract import ServiceDeliveryError
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import build_invoker, resolve_provider
from baseltest.declarative._services import (
    DEFAULT_DEADLINE_MS,
    LanguageModelParameters,
    _validate_configuration,
    resolved_provenance,
)

_BASE = {"system-prompt": "You are a service.", "model": "a-model"}


def _params(**overrides: object) -> LanguageModelParameters:
    return LanguageModelParameters(system_prompt="You are a service.", **overrides)  # type: ignore[arg-type]


# ── load-time validation (what `basel check` runs for zero samples) ───────────


def test_stated_deadline_loads() -> None:
    params = _validate_configuration("svc", {**_BASE, "deadline-ms": 30_000}, "the configuration")
    assert params.deadline_ms == 30_000


def test_unstated_deadline_resolves_to_the_default() -> None:
    params = _validate_configuration("svc", dict(_BASE), "the configuration")
    assert params.deadline_ms == DEFAULT_DEADLINE_MS


def test_the_default_is_finite() -> None:
    # The regression this whole key exists for: `None` means wait forever,
    # and forever is what a run was observed doing.
    assert isinstance(DEFAULT_DEADLINE_MS, int)
    assert DEFAULT_DEADLINE_MS > 0


@pytest.mark.parametrize("bad", ["30000", 1.5, True, 0, -1, None])
def test_out_of_range_or_wrong_type_is_refused(bad: object) -> None:
    with pytest.raises(ContractConfigurationError, match="deadline-ms"):
        _validate_configuration("svc", {**_BASE, "deadline-ms": bad}, "the configuration")


# ── fingerprinted identity (a changed deadline drifts a baseline) ─────────────


def test_deadline_is_in_identity_and_drives_drift() -> None:
    patient = resolved_provenance(_params(deadline_ms=600_000))
    impatient = resolved_provenance(_params(deadline_ms=5_000))
    assert patient["deadlineMs"] == "600000"
    assert impatient["deadlineMs"] == "5000"
    # A shorter deadline turns slow-but-delivered responses into failed
    # deliveries, so the two runs sample different streams and their
    # identities must diverge.
    assert patient != impatient


def test_unstated_deadline_is_still_recorded_in_identity() -> None:
    assert resolved_provenance(_params())["deadlineMs"] == str(DEFAULT_DEADLINE_MS)


# ── enforcement at the transport ──────────────────────────────────────────────


def test_a_peer_that_accepts_and_then_says_nothing_ends_the_sample(monkeypatch: Any) -> None:
    """The live failure shape, not a refused connection.

    A listening socket completes the handshake in the kernel's backlog and
    is never read from, so the request is accepted and then answered by
    silence — the 94-minute hang, in miniature. A connect-only deadline
    would not catch this.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        monkeypatch.setenv("MAVAI_LLM_ENDPOINT", f"http://127.0.0.1:{port}/v1/chat/completions")
        invoke = build_invoker(resolve_provider(None), _params(model="a-model", deadline_ms=250))
        started = time.perf_counter()
        with pytest.raises(ServiceDeliveryError, match="250ms deadline"):
            invoke("hello")
        assert time.perf_counter() - started < 10, "the deadline did not bound the read"


def test_a_deadline_striking_while_connecting_says_the_same_thing(monkeypatch: Any) -> None:
    """A connect-phase timeout arrives wrapped in URLError, and is the same fact."""

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setenv("MAVAI_LLM_ENDPOINT", "http://127.0.0.1:1/v1/chat/completions")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    invoke = build_invoker(resolve_provider(None), _params(model="a-model", deadline_ms=7_000))
    with pytest.raises(ServiceDeliveryError, match="7000ms deadline"):
        invoke("hello")


def test_an_unreachable_service_is_still_unreachable(monkeypatch: Any) -> None:
    """The other URLError causes keep their own statement: a refused
    connection is a fact about the service, not about our patience."""

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setenv("MAVAI_LLM_ENDPOINT", "http://127.0.0.1:1/v1/chat/completions")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    invoke = build_invoker(resolve_provider(None), _params(model="a-model"))
    with pytest.raises(ServiceDeliveryError, match="service unreachable at"):
        invoke("hello")


def test_the_deadline_reaches_the_transport(monkeypatch: Any) -> None:
    """Stated in seconds at the socket, milliseconds everywhere else."""
    seen: dict[str, Any] = {}

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        seen["timeout"] = kwargs.get("timeout")
        raise urllib.error.URLError("stop here")

    monkeypatch.setenv("MAVAI_LLM_ENDPOINT", "http://127.0.0.1:1/v1/chat/completions")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    invoke = build_invoker(resolve_provider(None), _params(model="a-model", deadline_ms=1_500))
    with pytest.raises(ServiceDeliveryError):
        invoke("hello")
    assert seen["timeout"] == 1.5
