"""Baseline artefact: record building, deterministic emission, valid YAML."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

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
        service_contract_id="refund-confirmation",
        service_name="refund-service",
        generated_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        confidence_level=0.95,
        inputs_identity="abc123def456",
        samples_planned=300,
        samples_executed=300,
        criteria={
            "relevant": CriterionCharacterisation(
                successes=294,
                trials=300,
                wilson_lower_bound=0.961796,
                failure_distribution={'response does not contain "refund"': 6},
                judgement=NormativeJudgement(
                    state="met", stipulated_threshold=0.95, confidence=0.95
                ),
            ),
            "measured": CriterionCharacterisation(successes=150, trials=300),
        },
        covariate_profile={"model": "small"},
        factor_record={"taskFormat": "mavai-contract/1"},
    )


class TestRendering:
    def test_deterministic(self) -> None:
        assert render_baseline(record()) == render_baseline(record())

    def test_parses_as_yaml_and_round_trips_content(self) -> None:
        from ruamel.yaml import YAML

        loaded = YAML(typ="safe", pure=True).load(render_baseline(record()))
        assert loaded["schemaVersion"] == "mavai-baseline-1"
        assert loaded["serviceContractId"] == "refund-confirmation"
        assert loaded["execution"]["samplesExecuted"] == 300
        assert loaded["serviceName"] == "refund-service"
        assert loaded["covariateProfile"]["model"] == "small"
        assert loaded["factorRecord"]["taskFormat"] == "mavai-contract/1"
        assert loaded["confidenceLevel"] == 0.95
        # The bound is stated by the emitter at the record's confidence.
        assert loaded["criteria"]["relevant"]["wilsonLowerBound"] == pytest.approx(
            0.961796, abs=1e-6
        )
        relevant = loaded["criteria"]["relevant"]
        assert relevant["successes"] == 294
        assert relevant["normativeJudgement"]["state"] == "met"
        # A sequence of entries, not a reason-keyed mapping.
        entry = relevant["failureDistribution"][0]
        assert entry["condition"] == 'response does not contain "refund"'
        assert entry["count"] == 6
        assert "normativeJudgement" not in loaded["criteria"]["measured"]

    def test_awkward_strings_are_quoted_safely(self) -> None:
        from ruamel.yaml import YAML

        tricky = BaselineRecord(
            service_contract_id="no: not — a 'plain' scalar",
            service_name="svc",
            confidence_level=0.95,
            samples_planned=1,
            samples_executed=1,
            generated_at=datetime(2026, 7, 6, tzinfo=UTC),
            inputs_identity="x",
            criteria={"c: tricky #name": CriterionCharacterisation(successes=0, trials=1)},
        )
        loaded = YAML(typ="safe", pure=True).load(render_baseline(tricky))
        assert loaded["serviceContractId"] == "no: not — a 'plain' scalar"
        assert "c: tricky #name" in loaded["criteria"]

    def test_latency_block_carries_family_shape_and_sorted_vector(self) -> None:
        from ruamel.yaml import YAML

        with_latency = BaselineRecord(
            service_contract_id="svc",
            service_name="svc",
            generated_at=datetime(2026, 7, 8, tzinfo=UTC),
            confidence_level=0.95,
            samples_planned=3,
            samples_executed=3,
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
        built = BaselineRecord.from_run_result(result, service_name="b")
        assert built.criteria["judged"].judgement is not None
        assert built.criteria["judged"].judgement.state == "met"
        assert built.criteria["measured"].judgement is None
        assert built.criteria["measured"].trials == 300
        assert built.service_name == "b"
        assert built.inputs_identity == result.inputs_identity

    def test_latency_summarises_recorded_samples(self) -> None:
        criterion = Criterion(name="ok", postconditions=(contains("ok"),))
        contract = ServiceContract(
            contract_id="svc", invoke=lambda v: f"ok {v}", criteria=(criterion,)
        )
        plan = RunPlan(samples=30, inputs=("a",), kind=RunKind.MEASURE)
        with_samples = BaselineRecord.from_run_result(
            execute(contract, plan, record_samples=True), "svc"
        )
        assert with_samples.latency is not None
        assert with_samples.latency.contributing_samples == 30
        assert len(with_samples.latency.sorted_passing_latencies_ms) == 30
        # p50/p90/p95 supported at n=30; p99 needs 100
        assert [k for k, _ in with_samples.latency.percentiles] == ["p50Ms", "p90Ms", "p95Ms"]
        without_samples = BaselineRecord.from_run_result(execute(contract, plan), "svc")
        assert without_samples.latency is None


class TestWriting:
    def test_writes_stable_filename_and_refreshes(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path / "baselines")
        assert path.name == "refund-confirmation.refund-service-abc123def456.yaml"
        assert path.read_text(encoding="utf-8").startswith("schemaVersion:")
        again = write_baseline(record(), tmp_path / "baselines")
        assert again == path
        assert len(list((tmp_path / "baselines").glob("*.yaml"))) == 1
