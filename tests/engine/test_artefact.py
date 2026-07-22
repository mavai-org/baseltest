"""The shared artefact-emission primitives, and their single-sourcing.

The scalar/factor/latency emitters are defined once in
``baseltest.engine.artefact`` and shared by every artefact writer. These
tests pin both their rendering and the fact that all three writers reference
the *one* definition — a guard against a duplicate emitter creeping back
(import-linter does not yet constrain the optimization package).
"""

from baseltest.baseline import writer as baseline_writer
from baseltest.engine import LatencyBlock, artefact
from baseltest.exploration import writer as exploration_writer
from baseltest.optimization import writer as optimization_writer


class TestSingleSource:
    """Every writer references the one definition — introspected via each
    module's namespace, since the names are imported, not re-exported."""

    def test_every_writer_shares_the_one_quote(self) -> None:
        assert vars(baseline_writer)["quote"] is artefact.quote
        assert vars(exploration_writer)["quote"] is artefact.quote
        assert vars(optimization_writer)["quote"] is artefact.quote

    def test_factor_and_scalar_emitters_are_shared(self) -> None:
        assert vars(exploration_writer)["factor_lines"] is artefact.factor_lines
        assert vars(optimization_writer)["factor_lines"] is artefact.factor_lines
        assert vars(optimization_writer)["scalar"] is artefact.scalar

    def test_latency_emitter_is_shared(self) -> None:
        assert vars(baseline_writer)["latency_lines"] is artefact.latency_lines
        assert vars(exploration_writer)["latency_lines"] is artefact.latency_lines


class TestRendering:
    def test_quote_json_quotes_awkward_strings(self) -> None:
        assert artefact.quote('a "b" \n c') == '"a \\"b\\" \\n c"'

    def test_scalar_preserves_native_types(self) -> None:
        assert artefact.scalar(None) == "null"
        assert artefact.scalar(True) == "true"
        assert artefact.scalar(7) == "7"
        assert artefact.scalar(0.7) == "0.7"
        assert artefact.scalar("small") == '"small"'

    def test_factor_lines_empty_when_no_factors(self) -> None:
        assert artefact.factor_lines(()) == []

    def test_factor_lines_render_at_indent(self) -> None:
        lines = artefact.factor_lines((("model", "small"), ("temperature", 0.7)), indent="    ")
        assert lines == [
            "    factors:",
            '      "model": "small"',
            '      "temperature": 0.7',
        ]

    def test_latency_lines_carry_percentiles_and_vector(self) -> None:
        latency = LatencyBlock(
            contributing_samples=2,
            total_samples=3,
            percentiles=(("p50Ms", 460),),
            sorted_passing_latencies_ms=(430, 460),
        )
        assert artefact.latency_lines(latency) == [
            "latency:",
            '  basis: "passing-samples"',
            "  contributingSamples: 2",
            "  totalSamples: 3",
            "  p50Ms: 460",
            "  sortedPassingLatenciesMs:",
            "    - 430",
            "    - 460",
        ]
