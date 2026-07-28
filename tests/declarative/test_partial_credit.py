"""The partial-credit keywords: `optional:` on a check, `optional-slack:` on
a criterion — parsing, refusals, and end-to-end evaluation through the
declarative reader."""

from decimal import Decimal

import pytest

from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._parser import parse_contract

HEADER = """
format: mavai-contract/1
contract: t
service: s
"""


def refusal(contract: str) -> str:
    with pytest.raises(ContractConfigurationError) as caught:
        parse_contract(HEADER + contract)
    return str(caught.value)


class TestParsing:
    def test_optional_and_slack_parse(self) -> None:
        declaration = parse_contract(
            HEADER
            + """
criteria:
  - threshold: 0.5
    optional-slack: 2
    postconditions:
      - contains: "x"
      - contains: "y"
        optional: true
inputs: ["a"]
"""
        )
        criterion = declaration.criteria[0]
        assert criterion.optional_slack == 2
        assert criterion.forms[0].optional is False
        assert criterion.forms[1].optional is True

    def test_percent_slack_parses_to_its_exact_decimal(self) -> None:
        declaration = parse_contract(
            HEADER
            + """
criteria:
  - threshold: 0.5
    optional-slack: "20%"
    postconditions:
      - contains: "x"
inputs: ["a"]
"""
        )
        assert declaration.criteria[0].optional_slack == Decimal("20")

    def test_per_input_expected_takes_optional(self) -> None:
        declaration = parse_contract(
            HEADER
            + """
criteria:
  - threshold: 0.5
    contains: "x"
inputs:
  - input: "a"
    expected:
      - contains: "y"
        optional: true
"""
        )
        ((_, _, (form,)),) = declaration.expected_pairs
        assert form.optional is True


class TestRefusals:
    def test_a_bare_fraction_is_refused(self) -> None:
        message = refusal(
            "criteria:\n  - threshold: 0.5\n    optional-slack: 0.2\n"
            '    contains: "x"\ninputs: ["a"]\n'
        )
        assert "a bare fraction is never guessed at" in message

    def test_a_negative_count_is_refused(self) -> None:
        message = refusal(
            "criteria:\n  - threshold: 0.5\n    optional-slack: -1\n"
            '    contains: "x"\ninputs: ["a"]\n'
        )
        assert "`optional-slack:`" in message

    def test_a_malformed_percentage_is_refused(self) -> None:
        message = refusal(
            'criteria:\n  - threshold: 0.5\n    optional-slack: "20 %%"\n'
            '    contains: "x"\ninputs: ["a"]\n'
        )
        assert "`optional-slack:`" in message

    def test_optional_false_is_refused(self) -> None:
        message = refusal(
            "criteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - contains: "x"\n        optional: false\ninputs: ["a"]\n'
        )
        assert "required is the default, not a spelling" in message

    def test_optional_on_parses_is_refused(self) -> None:
        message = refusal(
            "transforms:\n  doc: json\ncriteria:\n  - threshold: 0.5\n    postconditions:\n"
            '      - parses: doc\n        optional: true\ninputs: ["a"]\n'
        )
        assert "would be inert" in message
