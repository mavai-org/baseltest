"""Read-side: parse the single writer's emission; resolve by strict identity."""

from datetime import UTC, datetime
from pathlib import Path

from baseltest.baseline import (
    BaselineRecord,
    CriterionCharacterisation,
    NormativeJudgement,
    read_baseline,
    resolve_baseline,
    write_baseline,
)


def record(provenance: dict[str, str] | None = None) -> BaselineRecord:
    return BaselineRecord(
        contract_id="refund-confirmation",
        generated_at=datetime(2026, 7, 8, tzinfo=UTC),
        sample_count=300,
        inputs_identity="a" * 64,
        criteria={
            "relevant": CriterionCharacterisation(
                successes=294,
                trials=300,
                failure_distribution={"response does not contain 'refund'": 6},
                judgement=NormativeJudgement(
                    state="met", stipulated_threshold=0.95, confidence=0.95
                ),
            ),
            "well-formed": CriterionCharacterisation(
                successes=300, trials=300, failure_distribution={}, judgement=None
            ),
        },
        provenance=provenance
        or {"taskFormat": "mavai-task/1", "binding": "refund-service", "model": "small"},
    )


class TestRoundTrip:
    def test_written_artefact_reads_back(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path)
        stored = read_baseline(path)
        assert stored.contract_id == "refund-confirmation"
        assert stored.sample_count == 300
        assert stored.inputs_identity == "a" * 64
        assert stored.criteria["relevant"].successes == 294
        assert stored.criteria["well-formed"].trials == 300
        assert stored.provenance["model"] == "small"

    def test_wrong_schema_is_a_readable_error(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path)
        path.write_text(
            path.read_text().replace("baseltest-baseline-1", "other-schema-9"),
            encoding="utf-8",
        )
        import pytest

        with pytest.raises(ValueError, match="other-schema-9"):
            read_baseline(path)


class TestResolution:
    def test_match(self, tmp_path: Path) -> None:
        write_baseline(record(), tmp_path)
        resolution = resolve_baseline(
            tmp_path,
            "refund-confirmation",
            "a" * 64,
            {"taskFormat": "mavai-task/1", "binding": "refund-service", "model": "small"},
        )
        assert resolution.matched
        assert resolution.baseline is not None

    def test_missing_file_names_the_expected_path(self, tmp_path: Path) -> None:
        resolution = resolve_baseline(tmp_path, "refund-confirmation", "a" * 64, {})
        assert not resolution.matched
        assert resolution.reason is not None and "no baseline found" in resolution.reason
        assert "refund-confirmation-aaaaaaaaaaaa.yaml" in resolution.reason

    def test_covariate_drift_names_the_differing_keys(self, tmp_path: Path) -> None:
        write_baseline(record(), tmp_path)
        resolution = resolve_baseline(
            tmp_path,
            "refund-confirmation",
            "a" * 64,
            {"taskFormat": "mavai-task/1", "binding": "refund-service", "model": "LARGE"},
        )
        assert not resolution.matched
        assert resolution.reason is not None
        assert "different configuration" in resolution.reason
        assert resolution.mismatched_keys == ("model",)

    def test_volatile_keys_do_not_block_a_match(self, tmp_path: Path) -> None:
        write_baseline(
            record(
                {
                    "taskFormat": "mavai-task/1",
                    "binding": "refund-service",
                    "runMode": "measure",
                    "taskFile": "old-name.yaml",
                }
            ),
            tmp_path,
        )
        resolution = resolve_baseline(
            tmp_path,
            "refund-confirmation",
            "a" * 64,
            {"taskFormat": "mavai-task/1", "binding": "refund-service"},
        )
        assert resolution.matched
