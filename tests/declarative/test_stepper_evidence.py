"""Pooling postcondition standings into the evidence a stepper reasons about.

The unit under test is the seam the optimize loop crosses: the run already
computes per-``(input, check)`` standings, and a stepper is useless if it
receives them as rows to re-derive facts from. These tests assert the
pooling — by provenance, by form, by path — and the two properties the
pooling exists to guarantee: that an input-stated check never travels as
an input identity, and that a criterion's own tally stays the measured
unit.
"""

from baseltest.contract.evaluation import ObservedValue, PostconditionStanding, Provenance
from baseltest.declarative._runner._evidence import _pool


def standing(
    input_index: int = 0,
    postcondition: str = "contains 'hello'",
    provenance: Provenance = Provenance.CRITERION,
    form: str | None = "contains",
    path: str | None = None,
    passed: int = 0,
    failed: int = 1,
    skipped: int = 0,
    expected: str | None = None,
    observed: tuple[ObservedValue, ...] = (),
    optional: bool = False,
) -> PostconditionStanding:
    return PostconditionStanding(
        input_index=input_index,
        postcondition=postcondition,
        provenance=provenance,
        form=form,
        path=path,
        passed=passed,
        failed=failed,
        skipped=skipped,
        expected=expected,
        observed=observed,
        optional=optional,
    )


class TestPooling:
    def test_rows_sharing_provenance_form_and_path_pool_into_one_group(self) -> None:
        groups = _pool(
            [
                standing(input_index=0, failed=2),
                standing(input_index=1, failed=3),
                standing(input_index=2, failed=1),
            ]
        )
        assert len(groups) == 1
        assert groups[0].failed == 6
        assert groups[0].inputs == 3
        assert groups[0].checks == 1

    def test_provenance_separates_groups_that_share_a_form(self) -> None:
        # A criterion-stated check judges every sample; an input-stated one
        # judges its own input alone. Pooling them together would state one
        # figure out of six beside another out of twelve with nothing to
        # explain it — the distinction the standings carry exists for this.
        groups = _pool(
            [
                standing(provenance=Provenance.CRITERION, form="equals"),
                standing(provenance=Provenance.INPUT, form="equals", input_index=1),
            ]
        )
        assert {group.provenance for group in groups} == {"criterion", "input"}

    def test_form_separates_groups(self) -> None:
        groups = _pool([standing(form="contains"), standing(form="matches", failed=5)])
        assert [group.form for group in groups] == ["matches", "contains"]  # most failures first

    def test_path_separates_groups(self) -> None:
        groups = _pool(
            [
                standing(path="$.total", failed=1),
                standing(path="$.items[*].name", failed=4),
            ]
        )
        assert [group.path for group in groups] == ["$.items[*].name", "$.total"]

    def test_distinct_checks_are_counted_within_a_group(self) -> None:
        groups = _pool(
            [
                standing(postcondition="equals 'a'", provenance=Provenance.INPUT, form="equals"),
                standing(
                    postcondition="equals 'b'",
                    provenance=Provenance.INPUT,
                    form="equals",
                    input_index=1,
                ),
            ]
        )
        assert groups[0].checks == 2
        assert groups[0].inputs == 2

    def test_identical_observed_excerpts_add_their_counts(self) -> None:
        # The same excerpt seen under two rows is one observation about the
        # service, not two.
        groups = _pool(
            [
                standing(observed=(ObservedValue(excerpt="goodbye", count=2, held=False),)),
                standing(
                    input_index=1,
                    observed=(ObservedValue(excerpt="goodbye", count=3, held=False),),
                ),
            ]
        )
        assert groups[0].observed[0].excerpt == "goodbye"
        assert groups[0].observed[0].count == 5

    def test_failing_excerpts_come_first(self) -> None:
        groups = _pool(
            [
                standing(
                    passed=9,
                    failed=1,
                    observed=(
                        ObservedValue(excerpt="fine", count=9, held=True),
                        ObservedValue(excerpt="broken", count=1, held=False),
                    ),
                )
            ]
        )
        assert [value.excerpt for value in groups[0].observed] == ["broken", "fine"]

    def test_an_excerpt_that_both_held_and_did_not_keeps_both_facts(self) -> None:
        # The same returned value judged differently across trials is the
        # signal, not noise to collapse.
        groups = _pool(
            [
                standing(
                    observed=(
                        ObservedValue(excerpt="hello", count=1, held=True),
                        ObservedValue(excerpt="hello", count=2, held=False),
                    )
                )
            ]
        )
        assert len(groups[0].observed) == 2

    def test_a_group_is_optional_only_when_every_pooled_check_is(self) -> None:
        assert _pool([standing(optional=True), standing(optional=True, input_index=1)])[0].optional
        assert not _pool([standing(optional=True), standing(optional=False, input_index=1)])[
            0
        ].optional

    def test_distinct_expected_operands_are_carried_and_capped(self) -> None:
        # Carried faithfully at the seam for any consumer; the
        # prompt-engineer is what withholds them from its meta model.
        groups = _pool(
            [standing(input_index=index, expected=f"answer-{index}") for index in range(5)]
        )
        assert len(groups[0].expected) == 3
        assert groups[0].expected[0] == "answer-0"

    def test_an_empty_standings_list_pools_to_nothing(self) -> None:
        assert _pool([]) == ()
