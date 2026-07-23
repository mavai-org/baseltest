"""File-sourced input parts: external text, media to a bound service, path
resolution, provenance identity, and the phase boundaries."""

import hashlib
from pathlib import Path

import pytest

from baseltest import FileInput
from baseltest.declarative import Bindings, check_contract, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._parser import load_contract
from baseltest.engine import Verdict, inputs_fingerprint


def write_contract(tmp_path: Path, text: str, name: str = "contract.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestExternalText:
    def test_text_file_part_delivers_the_decoded_string(self, tmp_path: Path) -> None:
        (tmp_path / "brief.md").write_text("# House style\nbe terse", encoding="utf-8")
        seen: list[str] = []
        bindings = Bindings()

        @bindings.binding("writer")
        def writer(prompt: str) -> str:
            seen.append(prompt)
            return prompt

        contract = """
format: mavai-contract/1
contract: writer-echoes
service: writer
criteria:
  - threshold: 0.5
    contains: "House style"
inputs:
  - input: { text: { file: ./brief.md } }
    expected: { contains: "be terse" }
"""
        result = run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS
        assert seen and seen[0] == "# House style\nbe terse"

    def test_json_text_file_is_delivered_as_source_text_not_parsed(self, tmp_path: Path) -> None:
        (tmp_path / "payload.json").write_text('{"a": 1}', encoding="utf-8")
        seen: list[object] = []
        bindings = Bindings()

        @bindings.binding("echo")
        def echo(prompt: str) -> str:
            seen.append(prompt)
            return prompt

        contract = """
format: mavai-contract/1
contract: echoes-json
service: echo
criteria:
  - threshold: 0.5
    contains: "{"
inputs:
  - input: { text: { file: ./payload.json } }
    expected: { equals: '{"a": 1}' }
"""
        result = run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS
        # The raw source text, a str — never a decoded dict.
        assert seen and all(delivered == '{"a": 1}' for delivered in seen)
        assert isinstance(seen[0], str)


class TestMediaToBinding:
    def test_media_part_delivers_a_fileinput(self, tmp_path: Path) -> None:
        (tmp_path / "clip.wav").write_bytes(b"RIFF....audio-bytes")
        seen: list[object] = []
        bindings = Bindings()

        @bindings.binding("stt")
        def stt(audio: FileInput) -> str:
            seen.append(audio)
            return f"heard {audio.path.name}"

        contract = """
format: mavai-contract/1
contract: stt-hears
service: stt
criteria:
  - threshold: 0.5
    contains: "heard"
inputs:
  - input: { audio: ./clip.wav }
    expected: { contains: "clip.wav" }
"""
        result = run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS
        delivered = seen[0]
        assert isinstance(delivered, FileInput)
        assert delivered.kind == "audio"
        assert delivered.data == b"RIFF....audio-bytes"
        assert delivered.content_hash == hashlib.sha256(b"RIFF....audio-bytes").hexdigest()

    def test_paths_resolve_relative_to_the_contract_not_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "clip.wav").write_bytes(b"bytes")
        bindings = Bindings()

        @bindings.binding("stt")
        def stt(audio: FileInput) -> str:
            return "ok"

        contract = """
format: mavai-contract/1
contract: stt-hears
service: stt
criteria:
  - threshold: 0.5
    contains: "ok"
inputs:
  - { audio: ./clip.wav }
"""
        path = write_contract(tmp_path, contract)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)  # cwd has no clip.wav; resolution must use the contract dir
        result = run(path, emit=False, bindings=bindings)
        assert result.composite is Verdict.PASS


class TestLoadTimeFileChecks:
    MISSING = """
format: mavai-contract/1
contract: stt-hears
service: stt
criteria:
  - threshold: 0.5
    contains: "ok"
inputs:
  - { audio: ./absent.wav }
"""

    def test_missing_input_file_is_a_clear_load_error_naming_the_path(self, tmp_path: Path) -> None:
        path = write_contract(tmp_path, self.MISSING)
        with pytest.raises(ContractConfigurationError) as refusal:
            load_contract(path)
        message = str(refusal.value)
        assert "cannot read input file" in message
        assert "absent.wav" in message

    def test_check_verb_catches_a_missing_input_file(self, tmp_path: Path) -> None:
        path = write_contract(tmp_path, self.MISSING)
        with pytest.raises(ContractConfigurationError, match="absent.wav"):
            check_contract(path)


class TestBoundaries:
    def test_file_input_to_a_text_parameter_is_a_phase_error(self, tmp_path: Path) -> None:
        (tmp_path / "clip.wav").write_bytes(b"bytes")
        bindings = Bindings()

        @bindings.binding("texty")
        def texty(prompt: str) -> str:  # a text service handed a media part
            return prompt

        contract = """
format: mavai-contract/1
contract: texty-hears
service: texty
criteria:
  - threshold: 0.5
    contains: "x"
inputs:
  - { audio: ./clip.wav }
"""
        with pytest.raises(ContractConfigurationError) as refusal:
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)
        message = str(refusal.value)
        assert "typed `str`" in message
        assert "multimodal gateway" in message

    def test_multi_part_input_is_reserved_for_a_later_phase(self, tmp_path: Path) -> None:
        (tmp_path / "clip.wav").write_bytes(b"bytes")
        bindings = Bindings()

        @bindings.binding("stt")
        def stt(audio: FileInput) -> str:
            return "ok"

        contract = """
format: mavai-contract/1
contract: stt-hears
service: stt
criteria:
  - threshold: 0.5
    contains: "ok"
inputs:
  - input:
      - text: "listen to this:"
      - audio: ./clip.wav
    expected: { contains: "ok" }
"""
        with pytest.raises(ContractConfigurationError, match="reserved for a later phase"):
            run(write_contract(tmp_path, contract), emit=False, bindings=bindings)


class TestFileInputIdentity:
    def _fi(self, path: str, data: bytes, kind: str = "file") -> FileInput:
        return FileInput(Path(path), kind, data, hashlib.sha256(data).hexdigest())

    def test_content_not_path_feeds_the_fingerprint(self) -> None:
        same_a = self._fi("/x/a.bin", b"same-bytes")
        same_b = self._fi("/y/b.bin", b"same-bytes")  # different path, same content
        assert inputs_fingerprint((same_a,)) == inputs_fingerprint((same_b,))

    def test_the_fingerprint_moves_when_the_content_moves(self) -> None:
        one = self._fi("/x/a.bin", b"one")
        two = self._fi("/x/a.bin", b"two")  # same path, different content
        assert inputs_fingerprint((one,)) != inputs_fingerprint((two,))

    def test_a_file_corpus_never_collides_with_the_all_string_form(self) -> None:
        media = self._fi("/x/a.bin", b"hello")
        assert inputs_fingerprint((media,)) != inputs_fingerprint(("hello",))

    def test_end_to_end_same_bytes_different_path_share_an_identity(self, tmp_path: Path) -> None:
        template = """
format: mavai-contract/1
contract: stt-hears
service: stt
criteria:
  - threshold: 0.5
    contains: "ok"
inputs:
  - {{ audio: ./{clip} }}
"""
        (tmp_path / "one.wav").write_bytes(b"identical")
        (tmp_path / "two.wav").write_bytes(b"identical")
        (tmp_path / "three.wav").write_bytes(b"different")
        one = load_contract(write_contract(tmp_path, template.format(clip="one.wav"), "a.yaml"))
        two = load_contract(write_contract(tmp_path, template.format(clip="two.wav"), "b.yaml"))
        three = load_contract(write_contract(tmp_path, template.format(clip="three.wav"), "c.yaml"))
        assert inputs_fingerprint(one.inputs) == inputs_fingerprint(two.inputs)
        assert inputs_fingerprint(one.inputs) != inputs_fingerprint(three.inputs)
