"""Multimodal request assembly and the media capability gate."""

import base64
import hashlib
from pathlib import Path

import pytest

from baseltest import MessageParts
from baseltest.contract import FileInput, MediaKind
from baseltest.declarative import check_contract
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import require_media, resolve_provider
from baseltest.declarative._services import LanguageModelParameters

PARAMS = LanguageModelParameters(system_prompt="s", model="m")


def _fi(kind: MediaKind, name: str, data: bytes) -> FileInput:
    return FileInput(Path(name), kind, data, hashlib.sha256(data).hexdigest())


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _user_content(provider_name: str, user_input: object) -> object:
    provider = resolve_provider(provider_name)
    body = provider.body(PARAMS, "m", user_input)
    return body["messages"][-1]["content"]  # anthropic/openai user message is last


class TestOpenAICompatibleAssembly:
    def test_text_only_content_stays_the_plain_string(self) -> None:
        assert _user_content("openai", "hello") == "hello"

    def test_image_is_an_image_url_data_uri_block(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"PNGDATA")
        content = _user_content("openai", MessageParts(("look:", image)))
        assert content[0] == {"type": "text", "text": "look:"}  # type: ignore[index]
        assert content[1]["type"] == "image_url"  # type: ignore[index]
        assert content[1]["image_url"]["url"] == f"data:image/png;base64,{_b64(b'PNGDATA')}"  # type: ignore[index]

    def test_audio_is_an_input_audio_block_with_format_from_extension(self) -> None:
        audio = _fi(MediaKind.AUDIO, "clip.wav", b"WAV")
        content = _user_content("openai", audio)
        assert content[0] == {
            "type": "input_audio",
            "input_audio": {"data": _b64(b"WAV"), "format": "wav"},
        }  # type: ignore[index]

    def test_document_is_a_file_block(self) -> None:
        doc = _fi(MediaKind.DOCUMENT, "invoice.pdf", b"%PDF")
        content = _user_content("openai", doc)
        assert content[0]["type"] == "file"  # type: ignore[index]
        assert content[0]["file"]["filename"] == "invoice.pdf"  # type: ignore[index]
        assert content[0]["file"]["file_data"] == f"data:application/pdf;base64,{_b64(b'%PDF')}"  # type: ignore[index]

    def test_parts_keep_their_authored_order(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"P")
        content = _user_content("openai", MessageParts((image, "after")))
        assert content[0]["type"] == "image_url"  # type: ignore[index]
        assert content[1] == {"type": "text", "text": "after"}  # type: ignore[index]


class TestAnthropicAssembly:
    def test_image_is_a_base64_source_block(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"PNG")
        content = _user_content("anthropic", MessageParts(("see:", image)))
        assert content[1] == {  # type: ignore[index]
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": _b64(b"PNG")},
        }

    def test_document_is_a_document_source_block(self) -> None:
        doc = _fi(MediaKind.DOCUMENT, "a.pdf", b"%PDF")
        content = _user_content("anthropic", doc)
        assert content[0]["type"] == "document"  # type: ignore[index]
        assert content[0]["source"]["media_type"] == "application/pdf"  # type: ignore[index]


class TestOllamaAssembly:
    def test_images_ride_in_an_images_array_beside_the_text(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"IMG")
        message = resolve_provider("ollama").body(PARAMS, "m", MessageParts(("caption", image)))[
            "messages"
        ][-1]
        assert message["content"] == "caption"
        assert message["images"] == [_b64(b"IMG")]


class TestCapabilityGate:
    def test_declared_capability_admits_the_media(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"x")
        require_media(resolve_provider("openai"), frozenset({"image-input"}), image)  # no raise

    def test_undeclared_capability_is_refused(self) -> None:
        image = _fi(MediaKind.IMAGE, "a.png", b"x")
        with pytest.raises(ContractConfigurationError, match="image-input"):
            require_media(resolve_provider("openai"), None, image)

    def test_a_kind_the_provider_cannot_carry_is_refused(self) -> None:
        audio = _fi(MediaKind.AUDIO, "a.wav", b"x")  # anthropic has no audio block
        with pytest.raises(ContractConfigurationError, match="cannot carry"):
            require_media(resolve_provider("anthropic"), frozenset({"audio-input"}), audio)

    def test_the_plain_file_kind_has_no_model_form(self) -> None:
        blob = _fi(MediaKind.FILE, "a.bin", b"x")
        with pytest.raises(ContractConfigurationError, match="cannot carry"):
            require_media(resolve_provider("openai"), None, blob)


def _write(tmp_path: Path, services: str, contract: str) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"PNGDATA")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


_CONTRACT = """
format: mavai-contract/1
contract: vision-answers
service: vision
criteria:
  - threshold: 0.5
    contains: "x"
inputs:
  - - text: "what is in this image?"
    - image: ./a.png
"""


class TestPreflightIntegration:
    @pytest.fixture(autouse=True)
    def _credential_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # These tests validate the offline media gate, which sits behind a
        # credential-*presence* check (a keyless service is refused before the
        # gate is reached). A dummy key lets them reach the gate; no live call
        # is made (`check_contract` runs zero samples), so no real key is
        # needed. A test that genuinely calls a live API skips when the key is
        # absent — not the case here.
        monkeypatch.setenv("MAVAI_LLM_API_KEY", "not-a-real-key")

    def test_media_without_the_capability_is_refused_before_sampling(self, tmp_path: Path) -> None:
        services = """
format: mavai-services/1
services:
  vision:
    type: language-model
    configuration:
      system-prompt: "describe the image"
      model: gpt-4o
      provider: openai
"""
        with pytest.raises(ContractConfigurationError, match="image-input"):
            check_contract(_write(tmp_path, services, _CONTRACT))

    def test_media_with_the_capability_passes_the_gate(self, tmp_path: Path) -> None:
        services = """
format: mavai-services/1
services:
  vision:
    type: language-model
    configuration:
      system-prompt: "describe the image"
      model: gpt-4o
      provider: openai
      capabilities: [image-input]
"""
        # check runs every load-time join with zero samples; the media gate is one.
        facts = check_contract(_write(tmp_path, services, _CONTRACT))
        assert facts  # no refusal raised

    def test_declaring_an_unencodable_media_capability_is_refused_at_load(
        self, tmp_path: Path
    ) -> None:
        services = """
format: mavai-services/1
services:
  vision:
    type: language-model
    configuration:
      system-prompt: "describe the image"
      model: claude
      provider: anthropic
      capabilities: [audio-input]
"""
        with pytest.raises(ContractConfigurationError, match="audio-input"):
            check_contract(_write(tmp_path, services, _CONTRACT))
