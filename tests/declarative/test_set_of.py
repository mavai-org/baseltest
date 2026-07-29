"""The graded set claim: ``set-of:`` through the declarative surface.

Membership semantics — a set is a set: declared lists and the selection
judged as sets, duplicates collapsing to one entry (an operand duplicate
warns, never refuses); the stated arithmetic in every failure reason; the
reduce-to-a-sharper-form refusals; end to end through ``run``.
"""

import json
from pathlib import Path

import pytest

from baseltest.declarative import Bindings, run
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._parser import parse_contract
from baseltest.engine import Verdict
from baseltest.observation import RunObservation


def write_contract(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def contract_with(check: str) -> str:
    return f"""
format: mavai-contract/1
contract: graded-terms
service: doc-service
transforms:
  doc: json
criteria:
  - name: terms-are-the-agreed-set
    threshold: 0.5
    postconditions:
      - in: doc
        path: "$.terms[*]"
        set-of:
{check}
inputs:
  - "extract"
"""


def terms_service(*terms: str) -> Bindings:
    bindings = Bindings()
    payload = json.dumps({"terms": list(terms)})

    @bindings.binding("doc-service")
    def doc_service(request: str) -> str:
        return payload

    return bindings


def run_with(tmp_path: Path, check: str, *terms: str) -> "Verdict | None":
    contract = write_contract(tmp_path, contract_with(check))
    result = run(contract, emit=False, bindings=terms_service(*terms), samples=5)
    return result.composite


BASE = """\
          required: ["Grunddeckung"]
          optional: ["Glasbruch", "Wasserschaden", "Diebstahl"]
          min-present: 2
"""


class TestParsingRefusals:
    def refusal(self, check: str) -> str:
        with pytest.raises(ContractConfigurationError) as excinfo:
            parse_contract(contract_with(check))
        return str(excinfo.value)

    def test_overlapping_lists_are_a_contradiction_naming_the_member(self) -> None:
        message = self.refusal(
            '          required: ["Grunddeckung"]\n'
            '          optional: ["Grunddeckung", "Glasbruch"]\n'
        )
        assert "'Grunddeckung'" in message
        assert "in both `required:` and `optional:`" in message

    def test_min_present_beyond_the_optional_list_is_unsatisfiable(self) -> None:
        message = self.refusal(
            '          optional: ["Glasbruch", "Wasserschaden"]\n          min-present: 3\n'
        )
        assert "exceeds the `optional:` list's distinct size (2)" in message

    def test_min_present_saturating_the_optional_list_names_required(self) -> None:
        message = self.refusal(
            '          required: ["Grunddeckung"]\n'
            '          optional: ["Glasbruch", "Wasserschaden"]\n'
            "          min-present: 2\n"
        )
        assert "equals the `optional:` list's distinct size" in message
        assert "move them to `required:`" in message

    def test_without_optional_the_claim_has_a_sharper_name(self) -> None:
        message = self.refusal('          required: ["Grunddeckung", "Glasbruch"]\n')
        assert "states `equals-set:` — say that" in message

    def test_without_optional_and_extras_allowed_it_states_contains_set(self) -> None:
        message = self.refusal(
            '          required: ["Grunddeckung"]\n          refuse-extras: false\n'
        )
        assert "states `contains-set:` — say that" in message

    def test_an_empty_claim_is_vacuous(self) -> None:
        message = self.refusal("          refuse-extras: true\n")
        assert "states nothing" in message

    def test_a_bare_fraction_floor_is_never_guessed_at(self) -> None:
        message = self.refusal(
            '          optional: ["Glasbruch", "Wasserschaden", "Diebstahl"]\n'
            "          min-present: 0.8\n"
        )
        assert "a bare fraction is never guessed at" in message

    def test_unknown_operand_keys_are_refused(self) -> None:
        message = self.refusal(
            '          optional: ["Glasbruch", "Wasserschaden"]\n          minimum: 1\n'
        )
        assert "unknown key `minimum:`" in message

    def test_set_of_requires_a_path_under_a_declared_view(self) -> None:
        with pytest.raises(ContractConfigurationError) as excinfo:
            parse_contract(
                contract_with("          optional: [a, b]\n").replace(
                    '        path: "$.terms[*]"\n', ""
                )
            )
        assert "requires a `path:` under a declared view" in str(excinfo.value)

    def test_a_duplicated_member_warns_and_collapses(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parse_contract(
            contract_with(
                '          required: ["Grunddeckung"]\n'
                '          optional: ["Glasbruch", "Glasbruch", "Wasserschaden"]\n'
                "          min-present: 1\n"
            )
        )
        err = capsys.readouterr().err
        assert "lists 'Glasbruch' more than once" in err
        assert "duplicates collapse to one entry (likely a typo)" in err

    def test_min_present_saturation_counts_distinct_members(self) -> None:
        # Two distinct optional members after the duplicate collapses —
        # min-present: 2 saturates the deduped list, and is refused.
        message = self.refusal(
            '          required: ["Grunddeckung"]\n'
            '          optional: ["Glasbruch", "Glasbruch", "Wasserschaden"]\n'
            "          min-present: 2\n"
        )
        assert "equals the `optional:` list's distinct size (2)" in message


class TestJudgement:
    def test_the_graded_claim_holds(self, tmp_path: Path) -> None:
        verdict = run_with(tmp_path, BASE, "Grunddeckung", "Glasbruch", "Wasserschaden")
        assert verdict is Verdict.PASS

    def test_a_missing_required_member_fails_named(self, tmp_path: Path) -> None:
        contract = write_contract(tmp_path, contract_with(BASE))
        result = run(
            contract,
            emit=False,
            bindings=terms_service("Glasbruch", "Wasserschaden"),
            samples=5,
        )
        assert result.composite is Verdict.FAIL
        (reason,) = {
            entry.condition for entry in RunObservation.from_run_result(result).failure_distribution
        }
        assert "missing required: 'Grunddeckung'" in reason

    def test_too_few_optional_members_fail_with_the_arithmetic(self, tmp_path: Path) -> None:
        contract = write_contract(tmp_path, contract_with(BASE))
        result = run(
            contract, emit=False, bindings=terms_service("Grunddeckung", "Glasbruch"), samples=5
        )
        assert result.composite is Verdict.FAIL
        (reason,) = {
            entry.condition for entry in RunObservation.from_run_result(result).failure_distribution
        }
        assert "optional members present 1 of 3 (min-present 2)" in reason

    def test_an_unlisted_member_is_an_extra(self, tmp_path: Path) -> None:
        contract = write_contract(tmp_path, contract_with(BASE))
        result = run(
            contract,
            emit=False,
            bindings=terms_service("Grunddeckung", "Glasbruch", "Wasserschaden", "Erfunden"),
            samples=5,
        )
        assert result.composite is Verdict.FAIL
        (reason,) = {
            entry.condition for entry in RunObservation.from_run_result(result).failure_distribution
        }
        assert "extras: 'Erfunden'" in reason

    def test_extras_allowed_when_relaxed_visibly(self, tmp_path: Path) -> None:
        relaxed = BASE + "          refuse-extras: false\n"
        verdict = run_with(
            tmp_path, relaxed, "Grunddeckung", "Glasbruch", "Wasserschaden", "Erfunden"
        )
        assert verdict is Verdict.PASS

    def test_a_duplicated_subject_member_is_membership_never_an_extra(self, tmp_path: Path) -> None:
        # The lax ruling: a subject element appearing twice is one member
        # present — not invented content, not a second occurrence to police.
        verdict = run_with(
            tmp_path, BASE, "Grunddeckung", "Grunddeckung", "Glasbruch", "Wasserschaden"
        )
        assert verdict is Verdict.PASS

    def test_the_pure_subset_claim(self, tmp_path: Path) -> None:
        subset = '          optional: ["Glasbruch", "Wasserschaden", "Diebstahl"]\n'
        assert run_with(tmp_path, subset, "Glasbruch") is Verdict.PASS
        assert run_with(tmp_path, subset, "Glasbruch", "Erfunden") is Verdict.FAIL

    def test_the_percentage_floor_resolves_over_distinct_members(self, tmp_path: Path) -> None:
        percent = '          optional: ["a", "b", "c", "d"]\n          min-present: "50%"\n'
        assert run_with(tmp_path, percent, "a", "b") is Verdict.PASS
        assert run_with(tmp_path, percent, "a") is Verdict.FAIL

    def test_an_empty_selection_fails_a_required_claim(self, tmp_path: Path) -> None:
        assert run_with(tmp_path, BASE) is Verdict.FAIL
