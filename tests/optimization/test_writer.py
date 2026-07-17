"""The optimization writer: deterministic emission and its internal-consistency guards."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from baseltest.exploration import CriterionStatistics, ExplorationRecord, FailureEntry
from baseltest.optimization import (
    IterationCapture,
    OptimizationRecord,
    render_optimization,
    write_optimization,
)


def observation(successes: int, samples: int) -> ExplorationRecord:
    return ExplorationRecord(
        contract_id="support-agent-tuning",
        generated_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        factors=(),
        samples_planned=samples,
        samples_executed=samples,
        successes=successes,
        failure_distribution=(
            (FailureEntry(condition="no greeting", count=samples - successes),)
            if successes < samples
            else ()
        ),
        criteria={"says-hello": CriterionStatistics(passes=successes, fails=samples - successes)},
        total_time_ms=samples * 100,
    )


def capture(index: int, temperature: float, score: float) -> IterationCapture:
    return IterationCapture(
        index=index,
        factors=(("system-prompt", "You greet."), ("temperature", temperature)),
        score=score,
        observation=observation(successes=round(score * 4), samples=4),
    )


def record(**overrides: Any) -> OptimizationRecord:
    values: dict[str, Any] = {
        "contract_id": "support-agent-tuning",
        "experiment_id": "temperature-linear",
        "objective": "maximize",
        "scorer": "observed-pass-rate",
        "generated_at": datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        "iterations": (capture(0, 0.0, 0.5), capture(1, 0.1, 0.75)),
        "best_index": 1,
        "termination": "max-iterations",
        "stepper": (("name", "linear-sweep"), ("key", "temperature")),
    }
    values.update(overrides)
    return OptimizationRecord(**values)


def load(text: str) -> dict[str, Any]:
    document = YAML(typ="safe", pure=True).load(text)
    assert isinstance(document, dict)
    return document


class TestRenderOptimization:
    def test_the_document_carries_the_run_and_its_history(self) -> None:
        document = load(render_optimization(record()))
        assert document["schemaVersion"] == "mavai-optimize-1"
        assert document["serviceContractId"] == "support-agent-tuning"
        assert document["experimentId"] == "temperature-linear"
        assert document["objective"] == "MAXIMIZE"
        assert document["scorer"] == "observed-pass-rate"
        assert document["termination"] == "max-iterations"
        assert document["stepper"] == {"name": "linear-sweep", "key": "temperature"}
        assert [entry["iteration"] for entry in document["iterations"]] == [0, 1]
        assert document["iterations"][0]["factors"]["temperature"] == 0.0
        assert document["iterations"][0]["statistics"]["successes"] == 2

    def test_the_convergence_block_is_consistent_with_the_named_iteration(self) -> None:
        document = load(render_optimization(record()))
        convergence = document["convergence"]
        best = document["iterations"][convergence["bestIteration"]]
        assert convergence["totalIterations"] == 2
        assert convergence["bestScore"] == best["score"]
        assert convergence["bestFactors"] == best["factors"]

    def test_emission_is_deterministic(self) -> None:
        assert render_optimization(record()) == render_optimization(record())

    def test_a_record_without_iterations_is_a_defect(self) -> None:
        with pytest.raises(ValueError, match="at least one iteration"):
            render_optimization(record(iterations=(), best_index=0))

    def test_a_best_index_outside_the_history_is_a_defect(self) -> None:
        with pytest.raises(ValueError, match="not in the recorded history"):
            render_optimization(record(best_index=7))


class TestWriteOptimization:
    def test_the_artefact_lands_under_the_contract_named_by_the_run_id(
        self, tmp_path: Path
    ) -> None:
        path = write_optimization(record(), tmp_path)
        assert path == tmp_path / "support-agent-tuning" / "temperature-linear.yaml"
        assert load(path.read_text(encoding="utf-8"))["experimentId"] == "temperature-linear"

    def test_rerunning_refreshes_the_file_in_place(self, tmp_path: Path) -> None:
        first = write_optimization(record(), tmp_path)
        second = write_optimization(record(termination="stepper-stopped"), tmp_path)
        assert first == second
        assert load(second.read_text(encoding="utf-8"))["termination"] == "stepper-stopped"
