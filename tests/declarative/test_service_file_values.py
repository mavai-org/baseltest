"""File-sourced service configuration values: the text form and the mapping form.

``system-prompt: {file: …}`` substitutes the decoded string; a mapping-valued
key such as ``response-schema:`` substitutes the *parsed* document, so one
canonical schema export can be referenced from every service that shares it
instead of inlined per service. Both are resolved-as-used: the resolved value
is the covariate exactly as if it had been written inline, so moving a schema
between spellings is identity-neutral and a baseline survives the move.
"""

import json
from pathlib import Path

import pytest

from baseltest import Bindings
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._services._model import ServiceDefinition
from baseltest.declarative._services._parse import parse_services

SCHEMA = {
    "type": "object",
    "properties": {"roof": {"type": "string"}, "storeys": {"type": "integer"}},
    "required": ["roof"],
}

SERVICES = """\
format: mavai-services/1
services:
  extractor:
    type: language-model
    configuration:
      system-prompt: "Extract the building."
      response-schema: {schema}
"""


def _write(tmp_path: Path, schema: str, roots: str = "") -> Path:
    path = tmp_path / "mavai-services.yaml"
    path.write_text(
        SERVICES.format(schema=schema).replace(
            "format: mavai-services/1\n", "format: mavai-services/1\n" + roots
        ),
        encoding="utf-8",
    )
    return path


def _parse(path: Path) -> ServiceDefinition:
    return parse_services(path.read_text(encoding="utf-8"), Bindings()._registry, path)["extractor"]


class TestMappingFileValues:
    def test_a_referenced_json_export_becomes_the_parsed_schema(self, tmp_path: Path) -> None:
        (tmp_path / "buildings.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        definition = _parse(_write(tmp_path, "{ file: ./buildings.json }"))
        assert definition.configuration.response_schema == SCHEMA

    def test_a_referenced_yaml_file_becomes_the_parsed_schema(self, tmp_path: Path) -> None:
        (tmp_path / "buildings.yaml").write_text(
            "type: object\nproperties:\n  roof: {type: string}\n", encoding="utf-8"
        )
        definition = _parse(_write(tmp_path, "{ file: ./buildings.yaml }"))
        assert definition.configuration.response_schema == {
            "type": "object",
            "properties": {"roof": {"type": "string"}},
        }

    def test_an_inline_schema_is_not_mistaken_for_a_reference(self, tmp_path: Path) -> None:
        # A mapping key's inline value is itself a mapping — it must pass
        # through untouched, never be read as a malformed `{file:}` form.
        definition = _parse(_write(tmp_path, json.dumps(SCHEMA)))
        assert definition.configuration.response_schema == SCHEMA

    def test_the_form_resolves_in_an_exploration_delta(self, tmp_path: Path) -> None:
        (tmp_path / "one.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (tmp_path / "two.json").write_text(
            json.dumps({"type": "object", "properties": {"roof": {"type": "number"}}}),
            encoding="utf-8",
        )
        path = _write(tmp_path, "{ file: ./one.json }")
        path.write_text(
            path.read_text(encoding="utf-8")
            + "    explorations:\n      - response-schema: { file: ./two.json }\n",
            encoding="utf-8",
        )
        definition = _parse(path)
        assert definition.configuration.response_schema == SCHEMA
        assert definition.explorations[0].response_schema["properties"] == {
            "roof": {"type": "number"}
        }
        assert definition.swept_keys == ("response-schema",)


class TestIdentityIsUntouched:
    def test_inline_and_referenced_schemas_share_one_service_identity(self, tmp_path: Path) -> None:
        # Location never enters identity: the fingerprint is taken over the
        # parsed schema, so a baseline joins across the two spellings.
        (tmp_path / "buildings.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        referenced = _parse(_write(tmp_path, "{ file: ./buildings.json }"))
        inline = parse_services(SERVICES.format(schema=json.dumps(SCHEMA)), Bindings()._registry)[
            "extractor"
        ]
        assert referenced.type.provenance(referenced.configuration) == inline.type.provenance(
            inline.configuration
        )
        assert "responseSchemaFingerprint" in referenced.type.provenance(referenced.configuration)

    def test_a_key_order_difference_in_the_file_is_still_one_identity(self, tmp_path: Path) -> None:
        # The fingerprint canonicalises key order, so a re-serialised export
        # that reorders keys is the same population, not a drifted one.
        (tmp_path / "a.json").write_text(json.dumps(SCHEMA, sort_keys=True), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(SCHEMA, sort_keys=False), encoding="utf-8")
        first = _parse(_write(tmp_path, "{ file: ./a.json }"))
        second = _parse(_write(tmp_path, "{ file: ./b.json }"))
        assert first.type.provenance(first.configuration) == second.type.provenance(
            second.configuration
        )

    def test_a_different_schema_is_a_different_identity(self, tmp_path: Path) -> None:
        (tmp_path / "a.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (tmp_path / "b.json").write_text(
            json.dumps({"type": "object", "properties": {}}), encoding="utf-8"
        )
        first = _parse(_write(tmp_path, "{ file: ./a.json }"))
        second = _parse(_write(tmp_path, "{ file: ./b.json }"))
        assert first.type.provenance(first.configuration) != second.type.provenance(
            second.configuration
        )


class TestRootsCompose:
    def test_a_root_reference_reaches_the_shared_export(self, tmp_path: Path) -> None:
        (tmp_path / "generated").mkdir()
        (tmp_path / "generated" / "buildings.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        definition = _parse(
            _write(
                tmp_path,
                '{ file: "@generated/buildings.json" }',
                roots="roots:\n  generated: ./generated\n",
            )
        )
        assert definition.configuration.response_schema == SCHEMA

    def test_an_undeclared_root_is_refused_from_a_mapping_key(self, tmp_path: Path) -> None:
        with pytest.raises(ContractConfigurationError, match="undeclared root"):
            _parse(_write(tmp_path, '{ file: "@generated/buildings.json" }'))

    def test_a_root_used_only_by_a_mapping_key_is_not_dead(self, tmp_path: Path) -> None:
        # Use-tracking must see the mapping-key read, or the shared-export
        # arrangement would trip the dead-declaration refusal.
        (tmp_path / "generated").mkdir()
        (tmp_path / "generated" / "buildings.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        definition = _parse(
            _write(
                tmp_path,
                '{ file: "@generated/buildings.json" }',
                roots="roots:\n  generated: ./generated\n",
            )
        )
        assert definition.roots[0].name == "generated"


class TestRefusals:
    def test_a_file_holding_a_list_is_refused_naming_the_shape(self, tmp_path: Path) -> None:
        (tmp_path / "wrong.json").write_text('["not", "a", "mapping"]', encoding="utf-8")
        with pytest.raises(ContractConfigurationError) as refusal:
            _parse(_write(tmp_path, "{ file: ./wrong.json }"))
        message = str(refusal.value)
        assert "holds a list" in message
        assert "takes a mapping" in message
        assert "wrong.json" in message

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "empty.json").write_text("", encoding="utf-8")
        with pytest.raises(ContractConfigurationError, match="holds nothing"):
            _parse(_write(tmp_path, "{ file: ./empty.json }"))

    def test_malformed_yaml_is_refused_as_such(self, tmp_path: Path) -> None:
        (tmp_path / "broken.yaml").write_text(
            "type: object\n  properties: oops\n", encoding="utf-8"
        )
        with pytest.raises(ContractConfigurationError, match="not well-formed YAML"):
            _parse(_write(tmp_path, "{ file: ./broken.yaml }"))

    def test_a_missing_file_is_refused_naming_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(ContractConfigurationError) as refusal:
            _parse(_write(tmp_path, "{ file: ./absent.json }"))
        assert "cannot read file" in str(refusal.value)
        assert "absent.json" in str(refusal.value)

    def test_a_non_string_path_is_refused_as_a_malformed_file_form(self, tmp_path: Path) -> None:
        with pytest.raises(ContractConfigurationError, match="file form is"):
            _parse(_write(tmp_path, "{ file: 7 }"))

    def test_an_empty_path_is_refused_as_a_malformed_file_form(self, tmp_path: Path) -> None:
        with pytest.raises(ContractConfigurationError, match="file form is"):
            _parse(_write(tmp_path, '{ file: "" }'))


class TestUnresolvedPositions:
    """The `initial:` overlay is resolved past the loader's file-value seam, so
    a reference there would reach `parse` unread — a mapping that is not the
    schema, a string that is not the prompt. It is refused, never taken
    literally."""

    def _optimizing(self, tmp_path: Path, initial: str) -> Path:
        (tmp_path / "buildings.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        path = _write(tmp_path, "{ file: ./buildings.json }")
        path.write_text(
            path.read_text(encoding="utf-8")
            + "    optimizations:\n      - stepper: prompt-engineer\n"
            "        max-iterations: 3\n"
            f"        initial:\n          {initial}\n",
            encoding="utf-8",
        )
        return path

    def test_a_schema_reference_in_an_initial_overlay_is_refused(self, tmp_path: Path) -> None:
        path = self._optimizing(tmp_path, "response-schema: { file: ./buildings.json }")
        with pytest.raises(ContractConfigurationError) as refusal:
            _parse(path)
        message = str(refusal.value)
        assert "resolves only in `configuration:` and `explorations:`" in message
        assert "response-schema" in message

    def test_a_prompt_reference_in_an_initial_overlay_is_refused(self, tmp_path: Path) -> None:
        path = self._optimizing(tmp_path, "system-prompt: { file: ./prompt.txt }")
        with pytest.raises(ContractConfigurationError, match="resolves only in"):
            _parse(path)

    def test_an_inline_overlay_value_is_untouched(self, tmp_path: Path) -> None:
        path = self._optimizing(tmp_path, 'system-prompt: "A different job."')
        definition = _parse(path)
        assert definition.optimizations[0].initial == {"system-prompt": "A different job."}


class TestTextKeysAreUnchanged:
    def test_a_mapping_under_a_text_key_is_still_read_as_the_file_form(
        self, tmp_path: Path
    ) -> None:
        # A text key's inline value is a string, so any mapping there is an
        # attempted reference — its malformed spellings stay specifically named.
        path = tmp_path / "mavai-services.yaml"
        path.write_text(
            "format: mavai-services/1\nservices:\n  extractor:\n    type: language-model\n"
            "    configuration:\n      system-prompt: { fyle: ./prompt.txt }\n",
            encoding="utf-8",
        )
        with pytest.raises(ContractConfigurationError, match="file form is"):
            parse_services(path.read_text(encoding="utf-8"), Bindings()._registry, path)

    def test_a_referenced_prompt_still_arrives_as_text(self, tmp_path: Path) -> None:
        (tmp_path / "prompt.txt").write_text("Extract the building.", encoding="utf-8")
        path = tmp_path / "mavai-services.yaml"
        path.write_text(
            "format: mavai-services/1\nservices:\n  extractor:\n    type: language-model\n"
            "    configuration:\n      system-prompt: { file: ./prompt.txt }\n",
            encoding="utf-8",
        )
        definition = parse_services(path.read_text(encoding="utf-8"), Bindings()._registry, path)[
            "extractor"
        ]
        assert definition.configuration.system_prompt == "Extract the building."
