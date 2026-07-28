"""The value-comparison forms through the declarative surface.

Parsing refusals (operand shapes, the set-form addressing rule), the
multi-selection semantics both ways — a scalar form universal over a
wildcard path, a set form collective over the same path — and the
null-versus-absent distinction, end to end through ``run``.
"""

import json
from pathlib import Path

import pytest

from baseltest.declarative import Bindings, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._materialise import materialise
from baseltest.declarative._parser import parse_contract
from baseltest.engine import Verdict


def write_contract(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def contract_with(criteria: str) -> str:
    return f"""
format: mavai-contract/1
contract: value-comparison
service: doc-service
transforms:
  doc: json
{criteria}
inputs:
  - "annotate"
"""


class TestParsingRefusals:
    def refusal(self, criteria: str) -> str:
        with pytest.raises(ContractConfigurationError) as excinfo:
            parse_contract(contract_with(criteria))
        return str(excinfo.value)

    def test_numeric_operand_must_be_a_number_or_numeric_string(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.premium", eq: "twelve"}'
        )
        assert "takes a number or a numeric string" in message

    def test_is_null_takes_the_literal_true_only(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.gone", is-null: false}'
        )
        assert "takes the literal `true`" in message

    def test_a_set_form_requires_a_declared_view_and_a_path(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, equals-set: ["a", "b"]}'
        )
        assert "requires a `path:` under a declared view" in message

    def test_a_set_operand_lists_at_least_one_element(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.x", contains-set: []}'
        )
        assert "non-empty list of scalar values" in message

    def test_count_equals_takes_a_non_negative_integer(self) -> None:
        for operand in ("-1", "true", '"2"'):
            message = self.refusal(
                "criteria:\n  - threshold: 0.9\n    postconditions:\n"
                f'      - {{in: doc, path: "$.x", count-equals: {operand}}}'
            )
            assert "non-negative integer" in message

    def test_path_still_refused_on_satisfies(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.x", satisfies: looks-right}'
        )
        assert "string and value-comparison forms only" in message

    def test_a_set_form_is_not_a_criterion_level_key(self) -> None:
        message = self.refusal('criteria:\n  - threshold: 0.9\n    equals-set: ["a"]')
        assert "unknown key" in message

    def test_is_takes_a_boolean_only(self) -> None:
        for operand in ('"true"', "1", "null"):
            message = self.refusal(
                "criteria:\n  - threshold: 0.9\n    postconditions:\n"
                f'      - {{in: doc, path: "$.flag", is: {operand}}}'
            )
            assert "`is:` takes a boolean" in message

    def test_bare_equals_true_refusal_names_is(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.flag", equals: true}'
        )
        assert "`is: true` / `is: false`" in message

    def test_bare_equals_null_refusal_names_is_null(self) -> None:
        message = self.refusal(
            "criteria:\n  - threshold: 0.9\n    postconditions:\n"
            '      - {in: doc, path: "$.flag", equals: null}'
        )
        assert "`is-null: true`" in message


DOCUMENT = {
    "isIncluded": True,
    "premium": 2637.8,
    "holder": "Frau Beispiel",
    "status": "accepted",
    "cancellation-date": None,
    "rents": [{"amount": 1200}, {"amount": 950.5}],
}


def doc_bindings() -> Bindings:
    bindings = Bindings()

    @bindings.binding("doc-service")
    def annotate(request: str) -> str:
        return json.dumps(DOCUMENT)

    return bindings


def run_verdict(tmp_path: Path, criteria: str) -> Verdict:
    result = run(write_contract(tmp_path, contract_with(criteria)), bindings=doc_bindings())
    return result.composite


class TestMultiSelectionSemantics:
    def test_scalar_form_is_universal_over_a_wildcard_path(self, tmp_path: Path) -> None:
        held = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.rents[*].amount", gt: 0}',
        )
        assert held is Verdict.PASS
        # Universal: one selected value below the bar fails the trial.
        failed = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.rents[*].amount", gt: 1000}',
        )
        assert failed is Verdict.FAIL

    def test_set_form_is_collective_over_the_same_path(self, tmp_path: Path) -> None:
        held = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.rents[*].amount", equals-set: [950.50, 1200]}\n'
            '      - {in: doc, path: "$.rents[*].amount", count-equals: 2}',
        )
        assert held is Verdict.PASS
        failed = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.rents[*].amount", equals-set: [950.50]}',
        )
        assert failed is Verdict.FAIL


class TestNullVersusAbsent:
    def test_json_null_and_absent_both_hold(self, tmp_path: Path) -> None:
        held = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.cancellation-date", is-null: true}\n'
            '      - {in: doc, path: "$.no-such-field", is-null: true}',
        )
        assert held is Verdict.PASS

    def test_a_present_value_fails_is_null(self, tmp_path: Path) -> None:
        failed = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.status", is-null: true}',
        )
        assert failed is Verdict.FAIL


class TestLiteralExpectedValues:
    def test_values_as_they_appear_in_the_document(self, tmp_path: Path) -> None:
        # The whole point: no canonicalisation transform, the expected
        # values written exactly as the source document spells them.
        held = run_verdict(
            tmp_path,
            'criteria:\n  - threshold: 0.5\n    not-equals: "ERROR"\n    postconditions:\n'
            '      - {in: doc, path: "$.premium", eq: 2637.80}\n'
            '      - {in: doc, path: "$.holder", equals-ci: "frau  BEISPIEL"}\n'
            '      - {in: doc, path: "$.status", not-equals: "declined"}\n'
            '      - {in: doc, path: "$.isIncluded", is: true}',
        )
        assert held is Verdict.PASS

    def test_is_judges_identity_not_projection(self, tmp_path: Path) -> None:
        # The status field holds the string "accepted", not a boolean: is
        # fails it with a type reason rather than coercing anything.
        failed = run_verdict(
            tmp_path,
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - {in: doc, path: "$.status", is: true}',
        )
        assert failed is Verdict.FAIL

    def test_per_input_expected_takes_the_value_forms(self, tmp_path: Path) -> None:
        contract = """
format: mavai-contract/1
contract: value-comparison
service: doc-service
transforms:
  doc: json
criteria:
  - threshold: 0.5
    contains: "premium"
inputs:
  - input: "annotate"
    expected:
      - {in: doc, path: "$.rents[*].amount", contains-set: [1200]}
"""
        result = run(write_contract(tmp_path, contract), bindings=doc_bindings())
        assert result.composite is Verdict.PASS


class TestMaterialisation:
    def test_value_forms_emit_their_factories(self) -> None:
        declaration = parse_contract(
            contract_with(
                'criteria:\n  - threshold: 0.5\n    not-equals: "ERROR"\n'
                "    eq: 42\n    is-null: true\n    is: true\n    postconditions:\n"
                '      - {in: doc, path: "$.rents[*].amount", equals-set: [1200, 950.50]}'
            )
        )
        source = materialise(declaration)
        assert "not_equals('ERROR')" in source
        assert "eq(42)" in source
        assert "is_null()" in source
        assert "is_(True)" in source
        assert "equals_set([1200, 950.5])" in source
        compile(source, "materialised.py", "exec")
