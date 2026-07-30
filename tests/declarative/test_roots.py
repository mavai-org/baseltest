"""Named path anchors: the ``roots:`` block, ``@<name>/`` references, the
``MAVAI_ROOT_<NAME>`` override, and their identity/disclosure guarantees.

The corpus-bound refusal battery lives in the vendored conformance run;
these tests pin what the corpus cannot: relocation and override identity
(a root changes path resolution, never identity), the loader-level edges
(escape containment, the ``./@`` literal spelling, ambient overrides),
and the provenance disclosure shape.
"""

import shutil
from pathlib import Path

import pytest

from baseltest import Bindings
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._parser import load_contract
from baseltest.declarative._services._parse import parse_services
from baseltest.engine import inputs_fingerprint

CONTRACT = """\
format: mavai-contract/1
contract: reads-the-corpus
service: reader
roots:
  corpus: ./shared
criteria:
  - threshold: 0.9
    matches: '\\w'
inputs:
  - - text: { file: "@corpus/note.txt" }
"""

SERVICES = """\
format: mavai-services/1
roots:
  prompts: ./shared
services:
  reader:
    type: language-model
    configuration:
      system-prompt: { file: "@prompts/prompt.txt" }
"""


def _write_tree(root: Path, contract: str = CONTRACT) -> Path:
    (root / "shared").mkdir(parents=True)
    (root / "shared" / "note.txt").write_text("the note", encoding="utf-8")
    (root / "shared" / "prompt.txt").write_text("You read notes.", encoding="utf-8")
    path = root / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


class TestRootReferences:
    def test_root_reference_reads_through_the_anchor(self, tmp_path: Path) -> None:
        declaration = load_contract(_write_tree(tmp_path))
        assert declaration.inputs == ("the note",)

    def test_literal_at_filename_is_spelled_dot_slash(self, tmp_path: Path) -> None:
        path = _write_tree(
            tmp_path,
            CONTRACT.replace('file: "@corpus/note.txt"', 'file: "./@note.txt"').replace(
                "roots:\n  corpus: ./shared\n", ""
            ),
        )
        (tmp_path / "@note.txt").write_text("at-note", encoding="utf-8")
        assert load_contract(path).inputs == ("at-note",)

    def test_reference_climbing_out_of_its_root_is_refused(self, tmp_path: Path) -> None:
        path = _write_tree(
            tmp_path,
            CONTRACT.replace("@corpus/note.txt", "@corpus/../secret.txt"),
        )
        (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
        with pytest.raises(ContractConfigurationError, match="escapes its root"):
            load_contract(path)

    def test_bare_root_reference_names_no_file(self, tmp_path: Path) -> None:
        path = _write_tree(tmp_path, CONTRACT.replace("@corpus/note.txt", "@corpus"))
        with pytest.raises(ContractConfigurationError, match="a root is a directory"):
            load_contract(path)


class TestRelocationIdentity:
    def test_relocated_contract_and_corpus_share_the_inputs_identity(self, tmp_path: Path) -> None:
        # A file-sourced input contributes its content, never its path —
        # so moving contract + corpus together changes nothing.
        first = load_contract(_write_tree(tmp_path / "a"))
        shutil.copytree(tmp_path / "a", tmp_path / "elsewhere" / "b")
        second = load_contract(tmp_path / "elsewhere" / "b" / "contract.yaml")
        assert inputs_fingerprint(first.inputs) == inputs_fingerprint(second.inputs)

    def test_override_pointing_at_a_corpus_copy_shares_the_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = load_contract(_write_tree(tmp_path / "a"))
        copy = tmp_path / "detached-corpus"
        shutil.copytree(tmp_path / "a" / "shared", copy)
        monkeypatch.setenv("MAVAI_ROOT_CORPUS", str(copy))
        overridden = load_contract(tmp_path / "a" / "contract.yaml")
        assert inputs_fingerprint(baseline.inputs) == inputs_fingerprint(overridden.inputs)
        assert overridden.roots[0].overridden is True
        # Publication hygiene: the disclosure carries the declared value,
        # never the resolved override path.
        assert overridden.roots[0].declared == "./shared"
        assert str(copy) not in overridden.roots[0].declared

    def test_ambient_override_naming_no_declared_root_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAVAI_ROOT_ELSEWHERE", "/nowhere/at/all")
        declaration = load_contract(_write_tree(tmp_path))
        assert declaration.inputs == ("the note",)

    def test_override_must_still_resolve_to_a_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAVAI_ROOT_CORPUS", str(tmp_path / "missing"))
        with pytest.raises(
            ContractConfigurationError, match="not an existing directory"
        ) as refusal:
            load_contract(_write_tree(tmp_path))
        assert "MAVAI_ROOT_CORPUS" in str(refusal.value)


class TestServicesPromptFile:
    def test_file_prompt_resolves_as_used(self, tmp_path: Path) -> None:
        # The resolved string is the covariate exactly as if written
        # inline — same parameters, same fingerprint (resolved-as-used).
        path = _write_tree(tmp_path)
        services_path = tmp_path / "mavai-services.yaml"
        services_path.write_text(SERVICES, encoding="utf-8")
        inline = SERVICES.replace("roots:\n  prompts: ./shared\n", "").replace(
            'system-prompt: { file: "@prompts/prompt.txt" }', 'system-prompt: "You read notes."'
        )
        from_file = parse_services(
            services_path.read_text(encoding="utf-8"), Bindings()._registry, services_path
        )["reader"]
        from_inline = parse_services(inline, Bindings()._registry)["reader"]
        assert from_file.configuration.system_prompt == "You read notes."
        assert from_file.type.provenance(from_file.configuration) == from_inline.type.provenance(
            from_inline.configuration
        )
        assert path.exists()

    def test_prompt_file_in_exploration_delta_resolves_before_the_grid(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "prompt.txt").write_text("Baseline job.", encoding="utf-8")
        (tmp_path / "shared" / "variant.txt").write_text("Variant job.", encoding="utf-8")
        services_path = tmp_path / "mavai-services.yaml"
        services_path.write_text(
            SERVICES.replace(
                'system-prompt: { file: "@prompts/prompt.txt" }',
                'system-prompt: { file: "@prompts/prompt.txt" }\n'
                "    explorations:\n"
                '      - system-prompt: { file: "@prompts/variant.txt" }',
            ),
            encoding="utf-8",
        )
        definition = parse_services(
            services_path.read_text(encoding="utf-8"), Bindings()._registry, services_path
        )["reader"]
        assert definition.configuration.system_prompt == "Baseline job."
        assert definition.explorations[0].system_prompt == "Variant job."
        assert definition.swept_keys == ("system-prompt",)

    def test_optimize_baseline_sees_the_resolved_string(self, tmp_path: Path) -> None:
        # The prompt-tuning path is unaffected: iteration 0 sees the
        # resolved string; steppers propose plain-string replacements.
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "prompt.txt").write_text("Tune me.", encoding="utf-8")
        services_path = tmp_path / "mavai-services.yaml"
        services_path.write_text(
            SERVICES.replace(
                'system-prompt: { file: "@prompts/prompt.txt" }',
                'system-prompt: { file: "@prompts/prompt.txt" }\n'
                "    optimizations:\n"
                "      - stepper: prompt-engineer\n"
                "        max-iterations: 3",
            ),
            encoding="utf-8",
        )
        definition = parse_services(
            services_path.read_text(encoding="utf-8"), Bindings()._registry, services_path
        )["reader"]
        assert definition.configuration.system_prompt == "Tune me."
        assert definition.optimizations[0].stepper_name == "prompt-engineer"


class TestDisclosure:
    def test_contract_declaration_discloses_declared_value_and_flag(self, tmp_path: Path) -> None:
        declaration = load_contract(_write_tree(tmp_path))
        (disclosure,) = declaration.roots
        assert (disclosure.name, disclosure.declared, disclosure.overridden) == (
            "corpus",
            "./shared",
            False,
        )

    def test_measure_provenance_entries_are_declared_value_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from baseltest.declarative._runner._run import _roots_disclosure

        monkeypatch.setenv("MAVAI_ROOT_CORPUS", str(tmp_path / "elsewhere"))
        (tmp_path / "elsewhere").mkdir()
        (tmp_path / "elsewhere" / "note.txt").write_text("the note", encoding="utf-8")
        declaration = load_contract(_write_tree(tmp_path))
        entries = _roots_disclosure(declaration, {})
        assert entries == {
            "root.corpus": "./shared",
            "root.corpus.overridden": "true",
        }
        assert str(tmp_path / "elsewhere") not in str(entries)
