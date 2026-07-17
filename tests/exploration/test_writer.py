"""The exploration artefact: family schema, readable stems, deterministic emission."""

import io
from datetime import UTC, datetime

from ruamel.yaml import YAML

from baseltest.engine import SampleRecord
from baseltest.exploration import (
    CriterionStatistics,
    ExplorationRecord,
    FailureEntry,
    LatencyBlock,
    exploration_stem,
    render_exploration,
    write_exploration,
)


def record(
    factors: tuple[tuple[str, object], ...] = (("temperature", 0.7),),
    successes: int = 4,
    samples: int = 5,
) -> ExplorationRecord:
    return ExplorationRecord(
        contract_id="support-agent-tuning",
        generated_at=datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC),
        factors=factors,
        samples_planned=samples,
        samples_executed=samples,
        successes=successes,
        failure_distribution=(FailureEntry(condition="response is not valid JSON", count=1),),
        criteria={
            "answers-as-json": CriterionStatistics(passes=successes, fails=samples - successes)
        },
        total_time_ms=2500,
    )


def parse_yaml(text: str) -> dict:  # type: ignore[type-arg]
    yaml = YAML(typ="safe", pure=True)
    return yaml.load(io.StringIO(text))  # type: ignore[no-any-return]


class TestStems:
    def test_one_segment_per_factor_in_order(self) -> None:
        stem = exploration_stem((("model", "small-model"), ("temperature", 0.7)))
        assert stem == "model-small-model_temperature-0.7"

    def test_no_factors_is_the_baseline(self) -> None:
        assert exploration_stem(()) == "baseline"

    def test_awkward_characters_become_underscores_and_collapse(self) -> None:
        stem = exploration_stem((("system-prompt", "You are   (very) helpful!"),))
        assert stem == "system-prompt-You_are_very_helpful_"

    def test_long_values_truncate_with_a_disambiguating_hash(self) -> None:
        long_a = "You are a helpful shopping assistant answering questions."
        long_b = "You are a helpful shopping assistant answering queries."
        stem_a = exploration_stem((("system-prompt", long_a),))
        stem_b = exploration_stem((("system-prompt", long_b),))
        assert stem_a != stem_b  # the hash suffix disambiguates
        for stem in (stem_a, stem_b):
            prefix, _, suffix = stem.rpartition("-")
            assert prefix.startswith("system-prompt-You_are_a_helpful")
            assert len(suffix) == 4
            assert all(c in "0123456789abcdef" for c in suffix)

    def test_same_factors_always_produce_the_same_stem(self) -> None:
        factors = (("model", "small-model"), ("temperature", 0.0))
        assert exploration_stem(factors) == exploration_stem(factors)


class TestRendering:
    def test_family_schema_shape(self) -> None:
        data = parse_yaml(render_exploration(record()))
        assert data["schemaVersion"] == "mavai-explore-1"
        assert data["serviceContractId"] == "support-agent-tuning"
        assert data["configuration"] == "temperature-0.7"
        assert data["factors"] == {"temperature": 0.7}
        assert data["execution"] == {
            "samplesPlanned": 5,
            "samplesExecuted": 5,
            "terminationReason": "COMPLETED",
        }
        statistics = data["statistics"]
        assert statistics["successes"] == 4
        assert statistics["failures"] == 1
        assert statistics["observed"] == 0.8
        assert statistics["failureDistribution"] == [
            {"condition": "response is not valid JSON", "count": 1}
        ]
        assert statistics["criteria"]["answers-as-json"] == {
            "observedPassRate": 0.8,
            "pass": 4,
            "fail": 1,
            "inconclusive": 0,
        }
        assert data["cost"] == {"totalTimeMs": 2500, "avgTimePerSampleMs": 500}

    def test_factor_values_keep_their_native_yaml_types(self) -> None:
        data = parse_yaml(
            render_exploration(record(factors=(("temperature", 0.7), ("model", "m"))))
        )
        assert isinstance(data["factors"]["temperature"], float)
        assert isinstance(data["factors"]["model"], str)

    def test_descriptive_only_no_verdict_vocabulary(self) -> None:
        text = render_exploration(record())
        for word in ("verdict", "PASS", "FAIL", "threshold", "confidence", "bound"):
            assert word not in text

    def test_emission_is_deterministic(self) -> None:
        assert render_exploration(record()) == render_exploration(record())

    def test_no_factors_block_when_the_grid_has_one_point(self) -> None:
        assert "factors:" not in render_exploration(record(factors=()))


class TestWriting:
    def test_one_file_per_configuration_under_the_contract_directory(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = write_exploration(record(), tmp_path)
        assert path == tmp_path / "support-agent-tuning" / "temperature-0.7.yaml"
        assert path.is_file()

    def test_rerunning_the_same_grid_point_refreshes_in_place(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        write_exploration(record(successes=4), tmp_path)
        path = write_exploration(record(successes=5), tmp_path)
        files = list((tmp_path / "support-agent-tuning").glob("*.yaml"))
        assert files == [path]
        assert parse_yaml(path.read_text(encoding="utf-8"))["statistics"]["successes"] == 5

    def test_artefacts_from_one_grid_diff_cleanly(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        low = render_exploration(record(factors=(("temperature", 0.0),), successes=5))
        high = render_exploration(record(factors=(("temperature", 0.7),), successes=3))
        differing = [
            (a, b) for a, b in zip(low.splitlines(), high.splitlines(), strict=True) if a != b
        ]
        # Same line count, and the differing lines are exactly the
        # configuration name, the factor values, and the statistics that
        # depend on them.
        keys = {line_a.split(":")[0].strip().strip('"') for line_a, _ in differing}
        assert keys == {
            "configuration",
            "temperature",
            "observed",
            "successes",
            "failures",
            "observedPassRate",
            "pass",
            "fail",
        }


def sample(index: int = 0, passed: bool = True, ms: int = 40) -> SampleRecord:
    return SampleRecord(
        input_index=index,
        postconditions=(
            ("has content", "passed"),
            ("valid structure", "failed" if not passed else "passed"),
        ),
        execution_time_ms=ms,
        content='{"items": []}',
        passed=passed,
    )


class TestLatencyBlock:
    def test_present_with_gated_percentiles_when_samples_passed(self) -> None:
        r = record()
        r = ExplorationRecord(
            **{
                **{
                    f: getattr(r, f)
                    for f in (
                        "contract_id",
                        "generated_at",
                        "factors",
                        "samples_planned",
                        "samples_executed",
                        "successes",
                        "failure_distribution",
                        "criteria",
                        "total_time_ms",
                    )
                },
                "latency": LatencyBlock(
                    contributing_samples=4,
                    total_samples=5,
                    percentiles=(("p50Ms", 42),),
                    sorted_passing_latencies_ms=(38, 40, 42, 55),
                ),
                "samples": (),
            }
        )
        data = parse_yaml(render_exploration(r))
        latency = data["latency"]
        assert latency["basis"] == "passing-samples"
        assert latency["contributingSamples"] == 4
        assert latency["totalSamples"] == 5
        assert latency["p50Ms"] == 42
        # gated out at small n: no authoritative-looking noise
        for absent in ("p90Ms", "p95Ms", "p99Ms"):
            assert absent not in latency
        assert latency["sortedPassingLatenciesMs"] == [38, 40, 42, 55]

    def test_absent_when_nothing_passed(self) -> None:
        assert "latency:" not in render_exploration(record())


class TestResultProjection:
    def _record_with_samples(self) -> ExplorationRecord:
        r = record()
        return ExplorationRecord(
            **{
                **{
                    f: getattr(r, f)
                    for f in (
                        "contract_id",
                        "generated_at",
                        "factors",
                        "samples_planned",
                        "samples_executed",
                        "successes",
                        "failure_distribution",
                        "criteria",
                        "total_time_ms",
                        "latency",
                    )
                },
                "samples": (sample(0), sample(1, passed=False, ms=55)),
            }
        )

    def test_family_projection_shape(self) -> None:
        data = parse_yaml(render_exploration(self._record_with_samples()))
        projection = data["resultProjection"]
        first = projection["sample[0]"]
        assert first["inputIndex"] == 0
        assert first["postconditions"]["has content"] == "passed"
        assert first["executionTimeMs"] == 40
        assert first["content"] == '{"items": []}'
        second = projection["sample[1]"]
        assert second["postconditions"]["valid structure"] == "failed"

    def test_deterministic_diff_anchors_at_sample_boundaries(self) -> None:
        text = render_exploration(self._record_with_samples())
        # anchor = first 8 hex of SHA-256("{sampleIndex}:{inputIndex}") — the
        # family rule, so anchors match across artefacts of one grid.
        assert "# ────── anchor:ac72368a ──────" in text  # sha256("0:0")
        assert "# ────── anchor:d6b5915c ──────" in text  # sha256("1:1")
        anchor_line = next(line for line in text.splitlines() if "anchor:ac72368a" in line)
        sample_line = text.splitlines()[text.splitlines().index(anchor_line) + 1]
        assert sample_line.strip().startswith('"sample[0]"')
