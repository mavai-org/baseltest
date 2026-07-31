"""The usage-bearing reply seam at the declarative boundary: a provider
response carrying token usage flows through the declarative invoke to an
evaluated sample — text judged, counts on the outcome — and a
usage-silent response stays a plain string. The engine-side seam tests
cannot catch a severed declarative path; these run the provider invoke
itself."""

import io
import json
import urllib.request
from typing import Any

import pytest

from baseltest.contract import Criterion, Reply, ServiceContract, ServiceDeliveryError, contains
from baseltest.declarative._providers import build_invoker, resolve_provider
from baseltest.declarative._services import LanguageModelParameters
from baseltest.engine import RunKind, RunPlan, execute

USAGE_BEARING_BODY = {
    "choices": [{"message": {"content": "hello Alice"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
}
USAGE_SILENT_BODY = {"choices": [{"message": {"content": "hello Alice"}}]}


@pytest.fixture()
def invoker(monkeypatch: Any):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    parameters = LanguageModelParameters(
        system_prompt="terse", provider="openai", model="gpt-4o-mini", temperature=0.0
    )
    return build_invoker(resolve_provider("openai"), parameters)


def _respond(monkeypatch: Any, body: dict[str, Any]) -> None:
    class FakeResponse(io.BytesIO):
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _contract(invoke: Any) -> ServiceContract:
    return ServiceContract(
        contract_id="reply-passthrough-probe",
        invoke=invoke,
        criteria=(Criterion(name="greets", postconditions=(contains("hello"),)),),
    )


class TestInvokePassthrough:
    def test_a_usage_bearing_body_passes_the_reply_through_unwrapped(
        self, invoker: Any, monkeypatch: Any
    ) -> None:
        # The regression: the not-a-string guard must not classify the
        # framework's own Reply as a failed delivery.
        _respond(monkeypatch, USAGE_BEARING_BODY)
        reply = invoker("Alice")
        assert isinstance(reply, Reply)
        assert (reply.text, reply.total_tokens) == ("hello Alice", 15)

    def test_a_usage_silent_body_stays_a_plain_string(self, invoker: Any, monkeypatch: Any) -> None:
        _respond(monkeypatch, USAGE_SILENT_BODY)
        assert invoker("Alice") == "hello Alice"

    def test_null_content_beside_usage_counts_is_still_a_failed_delivery(
        self, invoker: Any, monkeypatch: Any
    ) -> None:
        # Usage counts do not make an empty body a delivered text: the
        # no-text guard applies to what the reply carries.
        _respond(
            monkeypatch,
            {
                "choices": [{"message": {"content": None}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )
        with pytest.raises(ServiceDeliveryError, match="no text content"):
            invoker("Alice")


class TestEvaluatedSample:
    def test_usage_counts_flow_to_the_evaluated_sample(
        self, invoker: Any, monkeypatch: Any
    ) -> None:
        _respond(monkeypatch, USAGE_BEARING_BODY)
        result = execute(
            _contract(invoker),
            RunPlan(kind=RunKind.MEASURE, samples=4, inputs=("Alice",)),
        )
        # The text was judged — no failed deliveries — and the counts
        # landed on the outcomes.
        assert result.overall_successes == 4
        assert result.total_tokens == 60  # 4 samples x (12 + 3)

    def test_a_usage_silent_run_stays_token_less_and_judged(
        self, invoker: Any, monkeypatch: Any
    ) -> None:
        _respond(monkeypatch, USAGE_SILENT_BODY)
        result = execute(
            _contract(invoker),
            RunPlan(kind=RunKind.MEASURE, samples=4, inputs=("Alice",)),
        )
        assert result.overall_successes == 4
        assert result.total_tokens == 0
