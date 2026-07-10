"""Provider failure classification: delivery failures are samples; rejections are defects."""

import io
import urllib.error
import urllib.request
from typing import Any

import pytest

from baseltest.contract import ServiceDeliveryError
from baseltest.declarative._providers import (
    ProviderResponseError,
    build_invoker,
    resolve_provider,
)
from baseltest.declarative._services import LanguageModelParameters


@pytest.fixture()
def invoker(monkeypatch: Any):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    parameters = LanguageModelParameters(
        system_prompt="terse", provider="openai", model="gpt-4o-mini", temperature=0.0
    )
    return build_invoker(resolve_provider("openai"), parameters)


def _raise(monkeypatch: Any, error: Exception) -> None:
    def urlopen(request: Any, *args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.openai.com",
        status,
        "err",
        hdrs=None,
        fp=io.BytesIO(body),  # type: ignore[arg-type]
    )


class TestClassification:
    def test_unreachable_is_a_failed_delivery(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, urllib.error.URLError("nodename nor servname provided"))
        with pytest.raises(ServiceDeliveryError, match="service unreachable at"):
            invoker("hello")

    def test_server_error_is_a_failed_delivery(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, _http_error(503, b"overloaded"))
        with pytest.raises(ServiceDeliveryError, match="HTTP 503"):
            invoker("hello")

    def test_client_error_is_a_rejection_defect(self, invoker: Any, monkeypatch: Any) -> None:
        _raise(monkeypatch, _http_error(401, b"bad key"))
        with pytest.raises(ProviderResponseError, match="HTTP 401"):
            invoker("hello")
