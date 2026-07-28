"""Postcondition standings: the descriptive per-(input, check) tally.

The standings aggregate the per-trial outcomes every evaluation already
computes — passed/failed/skipped counts and an observed fraction, keyed by
input and check. They are triage, never inference: no confidence interval,
no threshold, no per-check verdict, anywhere they surface.
"""

import re
from dataclasses import replace
from decimal import Decimal
from xml.etree import ElementTree

from baseltest.baseline import BaselineRecord, render_baseline
from baseltest.contract import Criterion, OptionalSlack, ServiceContract, contains
from baseltest.engine import RunKind, RunPlan, execute
from baseltest.observation import RunObservation, observation_lines
from baseltest.reporting.console import render_run
from baseltest.reporting.verdict_xml import render_verdict_record


def contract() -> ServiceContract[str]:
    return ServiceContract(
        contract_id="svc",
        invoke=lambda text: str(text),  # echoes, so input "a" passes and "b" fails
        criteria=(
            Criterion(name="c", postconditions=(contains("a"), contains("x")), threshold=0.5),
        ),
    )


def run(samples: int = 4, kind: RunKind = RunKind.MEASURE):  # type: ignore[no-untyped-def]
    return execute(contract(), RunPlan(samples=samples, inputs=("a", "b"), kind=kind))


class TestStandingsTally:
    def test_rows_are_keyed_by_input_and_check(self) -> None:
        result = run()
        standings = result.criterion_results[0].standings
        assert [(row.input_index, row.postcondition) for row in standings] == [
            (0, 'contains "a"'),
            (0, 'contains "x"'),
            (1, 'contains "a"'),
            (1, 'contains "x"'),
        ]

    def test_counts_and_fraction_reflect_the_trials(self) -> None:
        result = run()
        by_key = {
            (row.input_index, row.postcondition): row
            for row in result.criterion_results[0].standings
        }
        # Input "a": contains "a" holds on both trials; contains "x" never.
        assert by_key[(0, 'contains "a"')].passed == 2
        assert by_key[(0, 'contains "x"')].failed == 2
        assert by_key[(0, 'contains "a"')].observed_fraction == 1.0
        assert by_key[(0, 'contains "x"')].observed_fraction == 0.0

    def test_standings_accompany_test_runs_too(self) -> None:
        result = run(kind=RunKind.TEST)
        assert result.criterion_results[0].standings


class TestConsoleBlock:
    def test_measure_output_carries_the_standings_block(self) -> None:
        text = render_run(run())
        assert "standings (descriptive — counts, not verdicts):" in text
        assert 'input 1 · contains "a": 0/2 passed (0.00)' in text

    def test_the_block_is_descriptive_only(self) -> None:
        # The regression guard: the standings never acquire inference — no
        # interval, no threshold, no per-check verdict vocabulary.
        text = render_run(run())
        block = text[text.index("standings") :]
        for banned in ("confidence", "interval", "wilson", "bound", "threshold"):
            assert banned not in block.lower()
        # Verdict vocabulary may not appear inside the standings lines.
        for line in block.splitlines():
            if line.strip().startswith("input"):
                assert not re.search(r"\b(PASS|FAIL|INCONCLUSIVE)\b", line)


class TestPersistence:
    def test_the_verdict_record_carries_the_standings_element(self) -> None:
        text = render_verdict_record(run(kind=RunKind.TEST))
        root = ElementTree.fromstring(text)
        namespace = "{http://mavai.org/verdict/1.0}"
        blocks = root.findall(f"{namespace}postcondition-standings/{namespace}criterion")
        assert [b.get("name") for b in blocks] == ["c"]
        rows = {
            (int(r.get("input-index", "-1")), r.get("check")): r
            for r in blocks[0].findall(f"{namespace}row")
        }
        row = rows[(0, 'contains "a"')]
        assert (row.get("passed"), row.get("failed"), row.get("skipped")) == ("2", "0", "0")
        assert row.get("observed-fraction") == "1.0"
        # Required is the default: an unmarked check states optional="false".
        assert all(r.get("optional") == "false" for r in rows.values())
        # No slack declared -> no attribute; absence is not "0".
        assert blocks[0].get("optional-slack") is None
        # A row carries counts only — never inference attributes.
        assert not any(
            "verdict" in key or "interval" in key or "threshold" in key for key in row.attrib
        )

    def test_the_transitional_environment_carriage_is_gone(self) -> None:
        # 1.3 states standings once, in the element; the environment no
        # longer carries postcondition-standings:* entries.
        text = render_verdict_record(run(kind=RunKind.TEST))
        root = ElementTree.fromstring(text)
        namespace = "{http://mavai.org/verdict/1.0}"
        keys = [
            e.get("key") or "" for e in root.findall(f"{namespace}environment/{namespace}entry")
        ]
        assert not any(key.startswith("postcondition-standings:") for key in keys)

    def test_the_baseline_artefact_carries_the_standings_block(self) -> None:
        artefact = render_baseline(BaselineRecord.from_run_result(run()))
        assert "postconditionStandings:" in artefact
        assert '"contains \\"a\\""' in artefact or 'contains \\"a\\"' in artefact
        assert "observedFraction: 0.000000" in artefact

    def test_the_baseline_reader_tolerates_the_standings_block(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from baseltest.baseline import read_baseline, write_baseline

        path = write_baseline(BaselineRecord.from_run_result(run()), tmp_path)
        stored = read_baseline(path)
        assert stored.criteria["c"].trials == 4


class TestPartialCreditFacts:
    """The partial-credit facts travel with the tallies in every persisted
    shape — the flag stated per row, the declared budget verbatim."""

    def _contract(self, slack: OptionalSlack) -> ServiceContract[str]:
        return ServiceContract(
            contract_id="svc",
            invoke=lambda text: str(text),
            criteria=(
                Criterion(
                    name="c",
                    postconditions=(contains("a"), replace(contains("x"), required=False)),
                    threshold=0.5,
                    optional_slack=slack,
                ),
            ),
        )

    def _run(self, slack: OptionalSlack):  # type: ignore[no-untyped-def]
        return execute(
            self._contract(slack),
            RunPlan(samples=4, inputs=("a", "b"), kind=RunKind.TEST),
        )

    def test_the_flag_and_slack_state_verbatim_in_every_shape(self) -> None:
        result = self._run(OptionalSlack(percent=Decimal("20")))
        namespace = "{http://mavai.org/verdict/1.0}"

        root = ElementTree.fromstring(render_verdict_record(result))
        block = root.find(f"{namespace}postcondition-standings/{namespace}criterion")
        assert block is not None
        assert block.get("optional-slack") == "20%"
        flags = {
            (row.get("check"), row.get("optional")) for row in block.findall(f"{namespace}row")
        }
        assert ('contains "x"', "true") in flags
        assert ('contains "a"', "false") in flags

        artefact = render_baseline(BaselineRecord.from_run_result(result))
        assert 'optionalSlack: "20%"' in artefact
        assert "optional: true" in artefact
        assert "optional: false" in artefact

        observation = "\n".join(observation_lines(RunObservation.from_run_result(result)))
        assert 'optionalSlack: "20%"' in observation
        assert "optional: true" in observation
        assert "optional: false" in observation

    def test_a_count_budget_spells_its_digits(self) -> None:
        result = self._run(OptionalSlack(count=2))
        namespace = "{http://mavai.org/verdict/1.0}"
        root = ElementTree.fromstring(render_verdict_record(result))
        block = root.find(f"{namespace}postcondition-standings/{namespace}criterion")
        assert block is not None
        assert block.get("optional-slack") == "2"

    def test_an_undeclared_budget_states_nothing(self) -> None:
        # Absence is distinguishable from "0": no slack declared means no
        # optionalSlack key and no optional-slack attribute anywhere.
        result = run(kind=RunKind.TEST)
        namespace = "{http://mavai.org/verdict/1.0}"
        root = ElementTree.fromstring(render_verdict_record(result))
        block = root.find(f"{namespace}postcondition-standings/{namespace}criterion")
        assert block is not None
        assert block.get("optional-slack") is None
        assert "optionalSlack" not in render_baseline(BaselineRecord.from_run_result(result))
        assert "optionalSlack" not in "\n".join(
            observation_lines(RunObservation.from_run_result(result))
        )
