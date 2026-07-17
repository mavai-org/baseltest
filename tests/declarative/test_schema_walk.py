"""The path ↔ declared-shape join: static validation, per-trial validation, recording."""

import json
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import binding, run, transform
from baseltest.declarative._cli import main
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import ENV_ENDPOINT
from baseltest.declarative._registry import clear_registries
from baseltest.declarative._services import parse_services
from baseltest.statistics.verdict import Verdict


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


@pytest.fixture(autouse=True)
def llm_endpoint(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Resolvable service environment; no test here ever invokes it."""
    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")


SERVICES = """
format: mavai-services/1
services:
  extractor:
    type: language-model
    configuration:
      system-prompt: "extract statements"
      model: small-model
      response-schema:
        type: object
        additionalProperties: false
        required: [statements]
        properties:
          statements:
            type: array
            items:
              type: object
              additionalProperties: false
              required: [kind, grounded]
              properties:
                kind: { type: string }
                grounded: { type: boolean }
"""

CONTRACT = """
format: mavai-contract/1
contract: extraction-is-sound
service: extractor
transforms:
  parsed: json
criteria:
  - name: statements-are-typed
    threshold: 0.5
    postconditions:
      - in: parsed
        path: "$.statements[*].kind"
        matches: '\\w'
inputs: ["doc-1"]
"""


def write_files(tmp_path: Path, contract: str = CONTRACT, services: str = SERVICES) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(contract, encoding="utf-8")
    return contract_path


class TestResponseSchemaJoin:
    def test_mistyped_path_is_refused_naming_segment_and_nearest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        contract = CONTRACT.replace("$.statements[*].kind", "$.statments[*].kind")
        assert main(["check", str(write_files(tmp_path, contract=contract))]) == 2
        message = capsys.readouterr().err
        assert "1 path expression cannot resolve" in message
        assert "criterion 'statements-are-typed', postcondition 1" in message
        assert "$.statments[*].kind" in message
        assert "at `$.statments`" in message
        assert "`statments` names no declared key here (declared: statements)" in message
        assert "did you mean `statements`?" in message
        assert "response-schema of service 'extractor'" in message

    def test_every_failing_expression_is_itemised_in_one_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        contract = CONTRACT.replace(
            "path: \"$.statements[*].kind\"\n        matches: '\\w'",
            "path: \"$.statments[*].kind\"\n        matches: '\\w'\n"
            "      - in: parsed\n"
            '        path: "$.statements[*].knid"\n'
            "        matches: '\\w'",
        )
        assert main(["check", str(write_files(tmp_path, contract=contract))]) == 2
        message = capsys.readouterr().err
        assert "2 path expressions cannot resolve" in message
        assert "postcondition 1" in message and "postcondition 2" in message
        assert "did you mean `statements`?" in message
        assert "did you mean `kind`?" in message

    def test_run_refuses_at_load_before_any_invocation(self, tmp_path: Path) -> None:
        contract = CONTRACT.replace("$.statements[*].kind", "$.statments[*].kind")
        with pytest.raises(ContractConfigurationError, match="cannot resolve"):
            run(write_files(tmp_path, contract=contract), emit=False)

    def test_resolving_paths_yield_a_counting_fact_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["check", str(write_files(tmp_path))]) == 0
        out = capsys.readouterr().out
        assert (
            "ok: 1 path expression resolves against the response-schema of "
            "service 'extractor'" in out
        )

    def test_filter_expression_passes_unverified_visibly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        contract = CONTRACT.replace(
            "$.statements[*].kind", "$.statements[?@.grounded == true].kind"
        )
        assert main(["check", str(write_files(tmp_path, contract=contract))]) == 0
        out = capsys.readouterr().out
        assert "ok (unverified): path `$.statements[?@.grounded == true].kind`" in out
        assert "beyond static reach" in out

    def test_wildcard_into_a_non_array_is_refused_with_the_type(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        contract = CONTRACT.replace("$.statements[*].kind", "$.statements[*].kind[*]")
        assert main(["check", str(write_files(tmp_path, contract=contract))]) == 2
        message = capsys.readouterr().err
        assert "indexes into a value declared as string, which is not an array" in message

    def test_no_declared_schema_means_no_join(self, tmp_path: Path) -> None:
        services = SERVICES[: SERVICES.index("      response-schema:")]
        contract = CONTRACT.replace("$.statements[*].kind", "$.statments[*].kind")
        files = write_files(tmp_path, contract=contract, services=services)
        assert main(["check", str(files)]) == 0

    def test_a_path_valid_in_one_union_branch_verifies(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        services = SERVICES.replace(
            """      response-schema:
        type: object""",
            """      response-schema:
        anyOf:
          - type: string
          - type: object
            additionalProperties: false
            required: [statements]
            properties:
              statements:
                type: array
                items: { type: string }
        type: object""",
        )
        # The original object schema remains a branch via the wrapper residue;
        # the path resolves there — one resolving branch suffices.
        assert main(["check", str(write_files(tmp_path, services=services))]) == 0

    def test_open_object_passes_unverified_not_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        services = SERVICES.replace(
            "        additionalProperties: false\n        required", "        required", 1
        )
        contract = CONTRACT.replace("$.statements[*].kind", "$.statmentz[*].kind")
        files = write_files(tmp_path, contract=contract, services=services)
        assert main(["check", str(files)]) == 0
        assert "ok (unverified)" in capsys.readouterr().out


VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["invariants"],
    "properties": {
        "invariants": {
            "type": "object",
            "additionalProperties": False,
            "required": ["closedWorld"],
            "properties": {"closedWorld": {"type": "boolean"}},
        }
    },
}

DERIVED_CONTRACT = """
format: mavai-contract/1
contract: derived-view-contract
service: echo-service
transforms:
  verdict: derive-verdict
criteria:
  - name: closed-world-holds
    threshold: 0.5
    postconditions:
      - in: verdict
        path: "$.invariants.closedWorld"
        equals: "true"
inputs: ["a"]
"""


def register_echo_service() -> None:
    @binding("echo-service")
    def echo(value: str) -> str:
        return value


class TestOutputSchemaJoin:
    def test_mistyped_path_over_a_derived_view_is_refused(self, tmp_path: Path) -> None:
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract = DERIVED_CONTRACT.replace("$.invariants.closedWorld", "$.invariants.closedWord")
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(contract, encoding="utf-8")
        with pytest.raises(ContractConfigurationError) as refusal:
            run(contract_path, emit=False)
        message = str(refusal.value)
        assert "`closedWord` names no declared key here (declared: closedWorld)" in message
        assert "did you mean `closedWorld`?" in message
        assert "declared output schema of view 'verdict'" in message

    def test_resolving_derived_view_path_counts_in_check_facts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(DERIVED_CONTRACT, encoding="utf-8")
        assert main(["check", str(contract_path)]) == 0
        out = capsys.readouterr().out
        assert (
            "ok: 1 path expression resolves against the declared output schema "
            "of view 'verdict'" in out
        )

    def test_schema_violating_output_is_a_named_trial_failure(self, tmp_path: Path) -> None:
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": "yes"}}  # boolean expected

        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(DERIVED_CONTRACT, encoding="utf-8")
        result = run(contract_path, emit=False)
        assert result.composite is Verdict.FAIL
        tally = result.criterion_results[0].tally
        assert tally.successes == 0
        assert any(
            "violates its declared output schema" in reason and "closedWorld" in reason
            for reason in tally.failure_reasons
        )

    def test_schema_file_path_form_is_accepted(self, tmp_path: Path) -> None:
        register_echo_service()
        schema_file = tmp_path / "verdict-view.schema.json"
        schema_file.write_text(json.dumps(VERDICT_SCHEMA), encoding="utf-8")

        @transform("derive-verdict", output_schema=schema_file)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(DERIVED_CONTRACT, encoding="utf-8")
        result = run(contract_path, emit=False)
        assert result.composite is Verdict.PASS

    def test_malformed_declared_schema_is_refused_at_registration(self) -> None:
        with pytest.raises(ContractConfigurationError, match="not a valid JSON Schema"):

            @transform("derive-verdict", output_schema={"type": "verdict"})
            def derive(raw: str) -> dict[str, Any]:
                return {}

    def test_xpath_over_a_derived_view_has_no_schema_join(self, tmp_path: Path) -> None:
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract = DERIVED_CONTRACT.replace(
            'path: "$.invariants.closedWorld"\n        equals: "true"',
            'path: "/invariants/closedWorld"\n        equals: "true"',
        )
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(contract, encoding="utf-8")
        assert main(["check", str(contract_path)]) == 0  # no join, no refusal


class TestDescriptiveRecording:
    def test_fingerprint_lands_in_views_block_never_in_provenance(self, tmp_path: Path) -> None:
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract = DERIVED_CONTRACT.replace("    threshold: 0.5\n", "")
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(contract, encoding="utf-8")
        run(contract_path, mode="measure", samples=20, baseline_dir=tmp_path / "b", emit=False)
        content = next((tmp_path / "b").glob("*.yaml")).read_text(encoding="utf-8")
        assert "views:" in content
        assert '"verdict":' in content
        assert "outputSchemaFingerprint" in content
        provenance_block = content.split("provenance:")[1].split("views:")[0]
        assert "outputSchemaFingerprint" not in provenance_block

    def test_schema_change_is_not_drift_no_covariate_refusal(self, tmp_path: Path) -> None:
        # The output schema is instrument-side: it has no influence on the
        # service, so it is never a covariate — a changed schema must NOT
        # refuse an existing baseline.
        register_echo_service()

        @transform("derive-verdict", output_schema=VERDICT_SCHEMA)
        def derive(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        contract = DERIVED_CONTRACT.replace("    threshold: 0.5\n", "")
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(contract, encoding="utf-8")
        run(contract_path, mode="measure", samples=20, baseline_dir=tmp_path / "b", emit=False)

        clear_registries()
        register_echo_service()
        widened = {**VERDICT_SCHEMA, "required": []}

        @transform("derive-verdict", output_schema=widened)
        def derive_v2(raw: str) -> dict[str, Any]:
            return {"invariants": {"closedWorld": True}}

        result = run(contract_path, mode="test", baseline_dir=tmp_path / "b", emit=False)
        assert result.composite is Verdict.PASS  # judged against the baseline, no refusal


class TestAstShapePin:
    def test_compiled_query_exposes_the_segment_and_selector_types(self) -> None:
        # The static walk leans on jsonpath-rfc9535's AST classes; an
        # upstream reshuffle must be a loud failure here, never a silent
        # everything-passes-unverified degradation.
        import jsonpath_rfc9535 as jsonpath
        from jsonpath_rfc9535.segments import (
            JSONPathChildSegment,
            JSONPathRecursiveDescentSegment,
        )
        from jsonpath_rfc9535.selectors import (
            FilterSelector,
            IndexSelector,
            NameSelector,
            SliceSelector,
            WildcardSelector,
        )

        query = jsonpath.compile("$.a[0][*].b")
        kinds = [
            (type(segment), [type(selector) for selector in segment.selectors])
            for segment in query.segments
        ]
        assert kinds == [
            (JSONPathChildSegment, [NameSelector]),
            (JSONPathChildSegment, [IndexSelector]),
            (JSONPathChildSegment, [WildcardSelector]),
            (JSONPathChildSegment, [NameSelector]),
        ]
        assert query.segments[0].selectors[0].name == "a"
        assert query.segments[1].selectors[0].index == 0
        recursive = jsonpath.compile("$..a")
        assert type(recursive.segments[0]) is JSONPathRecursiveDescentSegment
        filtered = jsonpath.compile("$.a[?@.b > 1][1:3]")
        assert type(filtered.segments[1].selectors[0]) is FilterSelector
        assert type(filtered.segments[2].selectors[0]) is SliceSelector


class TestNoIdentityOverride:
    def test_response_schema_covariate_key_fails_the_unknown_key_check(self) -> None:
        # response-schema always influences the service, so it is always a
        # covariate — the format offers no key to opt out.
        with pytest.raises(ContractConfigurationError, match="response-schema-covariate"):
            parse_services(
                SERVICES.replace(
                    "      model: small-model",
                    "      model: small-model\n      response-schema-covariate: false",
                )
            )
