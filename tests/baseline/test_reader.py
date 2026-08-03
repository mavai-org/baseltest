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
from baseltest.engine import LatencyBlock


def record(provenance: dict[str, str] | None = None) -> BaselineRecord:
    return BaselineRecord(
        service_contract_id="refund-confirmation",
        service_name="refund-service",
        generated_at=datetime(2026, 7, 8, tzinfo=UTC),
        confidence_level=0.95,
        inputs_identity="a" * 64,
        samples_planned=300,
        samples_executed=300,
        criteria={
            "relevant": CriterionCharacterisation(
                successes=294,
                trials=300,
                wilson_lower_bound=0.961796,
                failure_distribution={"response does not contain 'refund'": 6},
                judgement=NormativeJudgement(
                    state="met", stipulated_threshold=0.95, confidence=0.95
                ),
            ),
            "well-formed": CriterionCharacterisation(
                successes=300, trials=300, failure_distribution={}, judgement=None
            ),
        },
        covariate_profile=provenance if provenance is not None else {"model": "small"},
        factor_record={"taskFormat": "mavai-contract/1"},
        latency=LatencyBlock(
            contributing_samples=294,
            total_samples=300,
            percentiles=(("p50Ms", 240), ("p90Ms", 480), ("p95Ms", 760), ("p99Ms", 1180)),
            sorted_passing_latencies_ms=tuple(range(100, 394)),
        ),
    )


class TestRoundTrip:
    def test_quoted_key_containing_the_separator_reads_back(self, tmp_path: Path) -> None:
        # A failure reason quoting a regex (or a covariate value) may itself
        # contain ": " — the split point is the decoded key's end, never the
        # first separator in the line.
        tricky = BaselineRecord(
            service_contract_id="triage",
            service_name="triage-assistant",
            generated_at=datetime(2026, 7, 16, tzinfo=UTC),
            confidence_level=0.95,
            samples_planned=50,
            samples_executed=50,
            inputs_identity="b" * 64,
            criteria={
                "routed": CriterionCharacterisation(
                    successes=44,
                    trials=50,
                    failure_distribution={
                        "response does not match /category: (billing|access)/": 6
                    },
                    judgement=None,
                )
            },
            covariate_profile={},
        )
        stored = read_baseline(write_baseline(tricky, tmp_path))
        assert stored.criteria["routed"].successes == 44

    def test_written_artefact_reads_back(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path)
        stored = read_baseline(path)
        assert stored.contract_id == "refund-confirmation"
        assert stored.sample_count == 300
        assert stored.inputs_identity == "a" * 64
        assert stored.criteria["relevant"].successes == 294
        assert stored.criteria["well-formed"].trials == 300
        assert stored.service_name == "refund-service"
        assert stored.covariate_profile["model"] == "small"
        assert stored.factor_record["taskFormat"] == "mavai-contract/1"
        assert stored.latency is not None
        assert stored.latency.basis == "passing-samples"
        assert stored.latency.contributing_samples == 294
        assert stored.latency.total_samples == 300
        assert dict(stored.latency.percentiles)["p95Ms"] == 760
        assert stored.latency.sorted_passing_latencies_ms == tuple(range(100, 394))

    def test_a_previous_generation_artefact_is_refused_with_the_regeneration_path(
        self, tmp_path: Path
    ) -> None:
        # The clean break: no dual-read. The diagnostic IS the migration
        # experience, so it must name what was found, what is expected, and
        # the verb that regenerates the file.
        import pytest

        path = write_baseline(record(), tmp_path)
        text = path.read_text(encoding="utf-8").replace(
            'schemaVersion: "mavai-baseline-1"', 'schemaVersion: "baseltest-baseline-2"'
        )
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError) as raised:
            read_baseline(path)
        message = str(raised.value)
        assert "mavai-baseline-1" in message
        assert "mavai-baseline-1" in message
        assert "basel measure" in message

    def test_an_edited_artefact_is_refused_by_its_fingerprint(self, tmp_path: Path) -> None:
        import pytest

        path = write_baseline(record(), tmp_path)
        text = path.read_text(encoding="utf-8").replace("successes: 294", "successes: 300")
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="contentFingerprint"):
            read_baseline(path)

    def test_wrong_schema_is_a_readable_error(self, tmp_path: Path) -> None:
        path = write_baseline(record(), tmp_path)
        path.write_text(
            path.read_text().replace("mavai-baseline-1", "other-schema-9"),
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
            "refund-service",
            "a" * 64,
            {"model": "small"},
        )
        assert resolution.matched
        assert resolution.baseline is not None

    def test_missing_file_names_the_expected_path(self, tmp_path: Path) -> None:
        resolution = resolve_baseline(
            tmp_path, "refund-confirmation", "refund-service", "a" * 64, {}
        )
        assert not resolution.matched
        assert resolution.reason is not None and "no baseline found" in resolution.reason
        assert "refund-confirmation.refund-service-aaaaaaaaaaaa.yaml" in resolution.reason

    def test_covariate_drift_names_the_differing_keys(self, tmp_path: Path) -> None:
        write_baseline(record(), tmp_path)
        resolution = resolve_baseline(
            tmp_path,
            "refund-confirmation",
            "refund-service",
            "a" * 64,
            {"model": "LARGE"},
        )
        assert not resolution.matched
        assert resolution.reason is not None
        assert "different configuration" in resolution.reason
        assert resolution.mismatched_keys == ("model",)

    def test_provenance_no_longer_participates_in_matching(self, tmp_path: Path) -> None:
        # Formerly "volatile keys do not block a match": provenance was
        # subtracted from the comparison by a key blocklist. Identity and
        # provenance are now separate fields in the artefact, so nothing
        # has to be subtracted — a run whose provenance differs entirely
        # still matches on the identity tuple.
        write_baseline(record({"model": "small"}), tmp_path)
        resolution = resolve_baseline(
            tmp_path, "refund-confirmation", "refund-service", "a" * 64, {"model": "small"}
        )
        assert resolution.matched
