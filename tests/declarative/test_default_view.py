"""The path-conditional default subject view (subject rule, 2026-07-27).

A path-less check omitting ``in:`` judges ``raw``, exactly as it always
did; a ``path:``-bearing check omitting ``in:`` resolves to the owning
criterion's single ``parses:`` view, else the contract's sole declared
transform, else a load refusal naming both fixes. An explicit ``in:``
always wins, and the resolved declaration is indistinguishable from the
spelled one.
"""

import pytest

from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._parser import parse_contract

HEADER = """
format: mavai-contract/1
contract: t
service: s
"""


def forms_of(contract: str):
    declaration = parse_contract(HEADER + contract)
    return declaration.criteria[0].forms


class TestResolution:
    def test_a_path_less_check_still_judges_raw(self) -> None:
        (form,) = forms_of(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - contains: "x"
inputs: ["a"]
"""
        )
        assert form.view == "raw"

    def test_a_path_check_resolves_to_the_criterion_parses_view(self) -> None:
        parses, resolved = forms_of(
            """
transforms:
  parsed: json
  envelope: xml
criteria:
  - threshold: 0.5
    postconditions:
      - parses: parsed
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert resolved.view == "parsed"

    def test_a_path_check_resolves_to_the_sole_transform(self) -> None:
        (form,) = forms_of(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert form.view == "parsed"

    def test_an_explicit_in_wins_over_the_default(self) -> None:
        parses, explicit = forms_of(
            """
transforms:
  parsed: json
  envelope: xml
criteria:
  - threshold: 0.5
    postconditions:
      - parses: parsed
      - in: envelope
        path: "/e/x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert explicit.view == "envelope"

    def test_a_resolved_check_is_identical_to_a_spelled_one(self) -> None:
        spelled = forms_of(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - in: parsed
        path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        defaulted = forms_of(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert spelled == defaulted

    def test_per_input_expected_resolves_against_the_single_criterion(self) -> None:
        declaration = parse_contract(
            HEADER
            + """
transforms:
  parsed: json
  envelope: xml
criteria:
  - threshold: 0.5
    postconditions:
      - parses: parsed
inputs:
  - input: "a"
    expected:
      - path: "$.x"
        equals: "1"
"""
        )
        ((_, _, (form,)),) = declaration.expected_pairs
        assert form.view == "parsed"

    def test_a_set_form_resolves_like_any_path_check(self) -> None:
        (form,) = forms_of(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.xs[*]"
        equals-set: ["a", "b"]
inputs: ["a"]
"""
        )
        assert form.view == "parsed"


class TestRefusals:
    def refusal(self, contract: str) -> str:
        with pytest.raises(ContractConfigurationError) as caught:
            parse_contract(HEADER + contract)
        return str(caught.value)

    def test_unresolvable_among_several_transforms(self) -> None:
        message = self.refusal(
            """
transforms:
  parsed: json
  envelope: xml
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert "no default view is resolvable" in message
        assert "add `in:`" in message
        assert "declare `parses:`" in message

    def test_unresolvable_with_no_views_at_all(self) -> None:
        message = self.refusal(
            """
criteria:
  - threshold: 0.5
    postconditions:
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert "no default view is resolvable" in message

    def test_several_parses_forms_name_no_anchor(self) -> None:
        message = self.refusal(
            """
transforms:
  parsed: json
  envelope: xml
criteria:
  - threshold: 0.5
    postconditions:
      - parses: parsed
      - parses: envelope
      - path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert "no default view is resolvable" in message

    def test_an_explicit_raw_beside_path_is_still_refused(self) -> None:
        message = self.refusal(
            """
transforms:
  parsed: json
criteria:
  - threshold: 0.5
    postconditions:
      - in: raw
        path: "$.x"
        equals: "1"
inputs: ["a"]
"""
        )
        assert "cannot target `raw`" in message
