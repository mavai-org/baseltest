"""Baseline artefact: record building, deterministic emission, valid YAML."""

from datetime import UTC, datetime
from pathlib import Path

from baseltest.baseline import (
    BaselineRecord,
    CriterionCharacterisation,
    NormativeJudgement,
    render_baseline,
    write_baseline,
)
from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import LatencyBlock, RunKind, RunPlan, execute


def latency() -> LatencyBlock:
    return LatencyBlock(
        contributing_samples=2,
        total_samples=3,
        percentiles=(("p50Ms", 240),),
        sorted_passing_latencies_ms=(180, 240),
    )


def record() -> BaselineRecord:
    return BaselineRecord(
        contract_id="refund-confirmation",
        generated_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        sample_count=300,
        inputs_identity="abc123def456",
        criteria={
            "relevant": CriterionCharacterisation(
                successes=294,
                trials=300,
                failure_distribution={'response does not contain "refund"': 6},
                judgement=NormativeJudgement(
                    state="met", stipulated_threshold=0.95, confidence=0.95
                ),
            ),
            "measured": CriterionCharacterisation(successes=150, trials=300),
        },
        provenance={"taskFormat": "mavai-contract/1", "binding": "refund-service"},
    )


class TestRendering:
    def test_deterministic(self) -> None:
        assert render_baseline(record()) == render_baseline(record())

    def test_parses_as_yaml_and_round_trips_content(self) -> None:
        from ruamel.yaml import YAML

        loaded = YAML(typ="safe", pure=True).load(render_baseline(record()))
        assert loaded["schemaVersion"] == "baseltest-baseline-2"
        assert loaded["contractId"] == "refund-confirmation"
        assert loaded["sampleCount"] == 300
        assert loaded["provenance"]["binding"] == "refund-service"
        relevant = loaded["criteria"]["relevant"]
        assert relevant["successes"] == 294
        assert relevant["normativeJudgement"]["state"] == "met"
        assert relevant["failureDistribution"]['response does not contain "refund"'] == 6
        assert "normativeJudgement" not in loaded["criteria"]["measured"]

    def test_awkward_strings_are_quoted_safely(self) -> None:
        from ruamel.yaml import YAML

        tricky = BaselineRecord(
            contract_id="no: not — a 'plain' scalar",
            generated_at=datetime(2026, 7, 6, tzinfo=UTC),
            sample_count=1,
            inputs_identity="x",
            criteria={"c: tricky #name": CriterionCharacterisation(successes=0, trials=1)},
        )
        loaded = YAML(typ="safe", pure=True).load(render_baseline(tricky))
        assert loaded["contractId"] == "no: not — a 'plain' scalar"
        assert "c: tricky #name" in loaded["criteria"]

    def test_latency_block_carries_family_shape_and_sorted_vector(self) -> None:
        from ruamel.yaml import YAML

        with_latency = BaselineRecord(
            contract_id="svc",
            generated_at=datetime(2026, 7, 8, tzinfo=UTC),
            sample_count=3,
            inputs_identity="x",
            criteria={"c": CriterionCharacterisation(successes=2, trials=3)},
            latency=latency(),
        )
        loaded = YAML(typ="safe", pure=True).load(render_baseline(with_latency))
        block = loaded["latency"]
        assert block["basis"] == "passing-samples"
        assert block["contributingSamples"] == 2
        assert block["totalSamples"] == 3
        assert block["p50Ms"] == 240
        # gated out at small n: no authoritative-looking noise
        for absent in ("p90Ms", "p95Ms", "p99Ms"):
            assert absent not in block
        assert block["sortedPassingLatenciesMs"] == [180, 240]

    def test_no_latency_block_when_nothing_passed(self) -> None:
        assert "latency:" not in render_baseline(record())


class TestFromRunResult:
    def test_thresholded_criteria_carry_judgement_others_do_not(self) -> None:
        judged = Criterion(name="judged", postconditions=(contains("ok"),), threshold=0.5)
        measured = Criterion(name="measured", postconditions=(contains("never"),))
        contract = ServiceContract(
            contract_id="svc", invoke=lambda v: f"ok {v}", criteria=(judged, measured)
        )
        result = execute(contract, RunPlan(samples=300, inputs=("a",), kind=RunKind.MEASURE))
        built = BaselineRecord.from_run_result(result, provenance={"binding": "b"})
        assert built.criteria["judged"].judgement is not None
        assert built.criteria["judged"].judgement.state == "met"
        assert built.criteria["measured"].judgement is None
        assert built.criteria["measured"].trials == 300
        assert built.provenance == {"binding": "b"}
        assert built.inputs_identity == result.inputs_identity

    def test_latency_summarises_recorded_samples(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("ok"),))
        contract = ServiceContract(
            contract_id="svc", invoke=lambda v: f"ok {v}", criteria=(criterion,)
        )
        plan = RunPlan(samples=30, inputs=("a",), kind=RunKind.MEASURE)
        with_samples = BaselineRecord.from_run_result(execute(contract, plan, record_samples=True))
        assert with_samples.latency is not None
        assert with_samples.latency.contributing_samples == 30
        assert len(with_samples.latency.sorted_passing_latencies_ms) == 30
        # p50/p90/p95 supported at n=30; p99 needs 100
        assert [k for k, _ in with_samples.latency.percentiles] == ["p50Ms", "p90Ms", "p95Ms"]
        without_samples = BaselineRecord.from_run_result(execute(contract, plan))
        assert without_samples.latency is None


class TestWriting:
    def test_writes_stable_filename_and_refreshes(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path / "baselines")
        assert path.name == "refund-confirmation-abc123def456.yaml"
        assert path.read_text(encoding="utf-8").startswith("schemaVersion:")
        again = write_baseline(record(), tmp_path / "baselines")
        assert again == path
        assert len(list((tmp_path / "baselines").glob("*.yaml"))) == 1
