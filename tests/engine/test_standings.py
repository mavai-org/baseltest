"""Postcondition standings: the descriptive per-(input, check) tally.

The standings aggregate the per-trial outcomes every evaluation already
computes — passed/failed/skipped counts and an observed fraction, keyed by
input and check. They are triage, never inference: no confidence interval,
no threshold, no per-check verdict, anywhere they surface.
"""

import json
import re
from xml.etree import ElementTree

from baseltest.baseline import BaselineRecord, render_baseline
from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import RunKind, RunPlan, execute
from baseltest.reporting.console import render_run
from baseltest.reporting.verdict_xml import STANDINGS_PREFIX, render_verdict_record


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
    def test_the_verdict_record_carries_standings_entries(self) -> None:
        text = render_verdict_record(run(kind=RunKind.TEST))
        root = ElementTree.fromstring(text)
        namespace = "{http://mavai.org/verdict/1.0}"
        entries = {
            e.get("key"): e.get("value")
            for e in root.findall(f"{namespace}environment/{namespace}entry")
        }
        value = entries[f"{STANDINGS_PREFIX}c"]
        assert value is not None
        rows = json.loads(value)
        assert {
            "input": 0,
            "check": 'contains "a"',
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "observedFraction": 1.0,
        } in rows
        assert not any("verdict" in row or "interval" in row for row in rows)

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
