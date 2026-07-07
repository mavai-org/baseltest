"""The exploration artefact: family schema, readable stems, deterministic emission."""

import io
from datetime import UTC, datetime

from ruamel.yaml import YAML

from baseltest.exploration import (
    CriterionStatistics,
    ExplorationRecord,
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
        failure_distribution={"response is not valid JSON": 1},
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
        assert data["schemaVersion"] == "punit-spec-1"
        assert data["useCaseId"] == "support-agent-tuning"
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
        assert statistics["failureDistribution"] == {"response is not valid JSON": 1}
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
        # Same line count, and the differing lines are exactly the factor
        # values and the statistics that depend on them.
        keys = {line_a.split(":")[0].strip().strip('"') for line_a, _ in differing}
        assert keys == {
            "temperature",
            "observed",
            "successes",
            "failures",
            "observedPassRate",
            "pass",
            "fail",
        }
