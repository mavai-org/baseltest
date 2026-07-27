"""The value-comparison forms: typed evaluation, decimal semantics, collectives."""

import pytest

from baseltest.contract import (
    contains_set,
    count_equals,
    eq,
    equals_ci,
    equals_set,
    ge,
    gt,
    is_,
    is_null,
    le,
    lt,
    ne,
    not_equals,
)


class TestNumericEquality:
    def test_formatting_insensitive_decimal_equality(self) -> None:
        check = eq("2637.80")
        assert check.evaluate(2637.8).passed
        assert check.evaluate("2637.8").passed
        assert check.evaluate("2.6378e3").passed
        assert check.evaluate("2637.800").passed

    def test_near_miss_fails(self) -> None:
        result = eq("273.50").evaluate("273.8")
        assert not result.passed
        assert result.reason is not None and "273.8" in result.reason

    def test_decimal_not_binary_float(self) -> None:
        # 0.1 + 0.2 style artefacts never decide a verdict: the operand
        # 0.3 equals the subject "0.3" exactly, as decimals.
        assert eq(0.3).evaluate("0.3").passed

    def test_ne_is_the_numeric_negation(self) -> None:
        assert ne(0).evaluate("0.1").passed
        assert not ne(0).evaluate("0.0").passed

    def test_non_numeric_subject_is_a_type_failure(self) -> None:
        for subject in ("twelve", {"a": 1}, [1], None, True):
            result = eq(1).evaluate(subject)
            assert not result.passed
            assert result.reason is not None and "not a number" in result.reason

    def test_non_numeric_operand_is_a_defect(self) -> None:
        with pytest.raises(ValueError):
            eq("twelve")


class TestOrdering:
    def test_strict_and_inclusive_boundaries(self) -> None:
        assert not lt(5).evaluate("5").passed
        assert le(5).evaluate("5.0").passed
        assert not gt(5).evaluate(5).passed
        assert ge(5).evaluate("5").passed
        assert lt("5").evaluate("4.999").passed
        assert gt(5).evaluate("5.001").passed


class TestTextForms:
    def test_equals_ci_folds_case_and_whitespace(self) -> None:
        check = equals_ci("Frau  Beispiel")
        assert check.evaluate("frau beispiel").passed
        assert check.evaluate("  FRAU\tBEISPIEL ").passed
        assert not check.evaluate("frau beispiele").passed

    def test_equals_ci_uses_unicode_case_folding(self) -> None:
        assert equals_ci("STRASSE").evaluate("straße").passed

    def test_equals_ci_folds_nothing_more(self) -> None:
        # No punctuation stripping, no article dropping — that
        # aggressiveness belongs to the graded operators.
        assert not equals_ci("the answer").evaluate("answer").passed
        assert not equals_ci("answer.").evaluate("answer").passed

    def test_not_equals_is_exact(self) -> None:
        assert not_equals("declined").evaluate("accepted").passed
        assert not not_equals("declined").evaluate("declined").passed
        # Exact, not folded: a case difference already differs.
        assert not_equals("declined").evaluate("Declined").passed

    def test_text_forms_need_text(self) -> None:
        for check in (equals_ci("x"), not_equals("x")):
            result = check.evaluate(7)
            assert not result.passed
            assert result.reason is not None and "string form judges text" in result.reason


class TestIsNull:
    def test_json_null_holds(self) -> None:
        assert is_null().evaluate(None).passed

    def test_the_string_null_does_not(self) -> None:
        result = is_null().evaluate("null")
        assert not result.passed
        assert result.reason is not None and "'null'" in result.reason

    def test_other_values_do_not(self) -> None:
        assert not is_null().evaluate(0).passed
        assert not is_null().evaluate("").passed


class TestIs:
    def test_boolean_identity(self) -> None:
        assert is_(True).evaluate(True).passed
        assert is_(False).evaluate(False).passed
        assert not is_(True).evaluate(False).passed

    def test_never_the_string_or_numeric_projection(self) -> None:
        for subject in ("true", "false", 1, 0, None):
            result = is_(True).evaluate(subject)
            assert not result.passed
            assert result.reason is not None
        # The projections are type failures, not mere mismatches.
        assert "not a boolean" in str(is_(True).evaluate("true").reason)
        assert "not a boolean" in str(is_(False).evaluate(0).reason)


class TestEqualsSet:
    def test_order_independent(self) -> None:
        check = equals_set(["a", "b"])
        assert check.evaluate(["b", "a"]).passed

    def test_duplicates_significant(self) -> None:
        check = equals_set(["a", "a", "b"])
        assert check.evaluate(["a", "b", "a"]).passed
        assert not check.evaluate(["a", "b"]).passed
        assert not check.evaluate(["a", "b", "b"]).passed

    def test_numbers_compare_numerically(self) -> None:
        assert equals_set([1200, 950.50]).evaluate([950.5, 1200.0]).passed

    def test_a_number_never_equals_its_string_spelling(self) -> None:
        assert not equals_set([1200]).evaluate(["1200"]).passed
        assert not equals_set(["1200"]).evaluate([1200]).passed

    def test_booleans_and_null_by_identity(self) -> None:
        assert equals_set([True, None]).evaluate([None, True]).passed
        # A boolean is not the number it would coerce to.
        assert not equals_set([True]).evaluate([1]).passed

    def test_non_selection_subject_is_a_type_failure(self) -> None:
        result = equals_set(["a"]).evaluate("a")
        assert not result.passed
        assert result.reason is not None and "not a selection" in result.reason


class TestContainsSet:
    def test_all_of_holds_over_a_superset(self) -> None:
        check = contains_set([1200, 950.50])
        assert check.evaluate([950.5, 7, 1200]).passed

    def test_a_missing_element_fails(self) -> None:
        result = contains_set([1200, 950.50]).evaluate([1200])
        assert not result.passed
        assert result.reason is not None and "do not contain" in result.reason

    def test_operand_multiplicity_binds(self) -> None:
        check = contains_set(["a", "a"])
        assert check.evaluate(["a", "b", "a"]).passed
        assert not check.evaluate(["a", "b"]).passed


class TestCountEquals:
    def test_exact_cardinality(self) -> None:
        assert count_equals(2).evaluate(["x", "y"]).passed
        assert not count_equals(2).evaluate(["x"]).passed

    def test_zero_holds_over_the_empty_selection(self) -> None:
        assert count_equals(0).evaluate([]).passed
        assert not equals_set(["a"]).evaluate([]).passed
