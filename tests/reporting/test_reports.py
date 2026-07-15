"""The HTML reports: family structure, self-containment, artefact-only inputs."""

from pathlib import Path

from baseltest.contract import Criterion, LatencyBar, LatencyBound, ServiceContract, contains
from baseltest.engine import RunKind, RunPlan, execute
from baseltest.reporting import (
    BaselineDisclosure,
    ClaimDisclosure,
    RunDesign,
    SizingDisclosure,
    parse_verdict_record,
    read_exploration_directory,
    read_verdict_directory,
    render_exploration_report,
    render_test_report,
    render_verdict_record,
    write_verdict_record,
)

EXPLORATION = """\
schemaVersion: "mavai-explore-1"
serviceContractId: "svc"
configuration: "model-{model}"
generatedAt: "2026-07-09T12:00:00+00:00"
factors:
  "model": "{model}"
execution:
  samplesPlanned: 5
  samplesExecuted: 5
  terminationReason: "COMPLETED"
statistics:
  observed: {rate}
  successes: {successes}
  failures: {failures}
  criteria:
    "answers-as-json":
      observedPassRate: {rate}
      pass: {successes}
      fail: {failures}
      inconclusive: 0
cost:
  totalTimeMs: 2500
  avgTimePerSampleMs: {avg}
latency:
  basis: "passing-samples"
  contributingSamples: {successes}
  totalSamples: 5
  p50Ms: {p50}
  sortedPassingLatenciesMs:
{vector}
"""


def write_variant(root: Path, model: str, rate: float, successes: int, p50: int, avg: int) -> None:
    latencies = [p50 - 2, p50 - 1, p50, p50 + 1, p50 + 2][:successes]
    vector = "\n".join(f"    - {v}" for v in latencies)
    (root / "svc").mkdir(parents=True, exist_ok=True)
    (root / "svc" / f"model-{model}.yaml").write_text(
        EXPLORATION.format(
            model=model,
            rate=rate,
            successes=successes,
            failures=5 - successes,
            avg=avg,
            p50=p50,
            vector=vector,
        ),
        encoding="utf-8",
    )


def run_record(passing: bool = True):  # type: ignore[no-untyped-def]
    contract = ServiceContract(
        contract_id="svc",
        invoke=lambda v: "ok" if passing else "nope",
        criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
        latency=LatencyBar(bounds=(LatencyBound("p50", 60_000),)),
    )
    result = execute(contract, RunPlan(samples=10, inputs=("a",), kind=RunKind.TEST))
    return parse_verdict_record(render_verdict_record(result))


class TestTestReport:
    def test_family_structure_and_self_containment(self) -> None:
        html = render_test_report([run_record()])
        assert "<title>basel Test Report</title>" in html
        assert "--pass-color: #2e7d32" in html and "--fail-color: #c62828" in html
        for column in (
            "<th>Test Name</th>",
            "<th>Verdict</th>",
            "<th>Functional</th>",
            "<th>p50</th>",
            "<th>p95</th>",
            "<th>p99</th>",
            "<th>Samples</th>",
            "<th>Elapsed</th>",
        ):
            assert column in html
        assert "Statistical assumptions and limitations" in html
        assert (
            "The required count is derived from the baseline at the stated confidence; "
            "a criterion passes when its passed count reaches it." in html
        )
        assert "<script" not in html and "http://" not in html and "https://" not in html
        assert 'class="basel-pass"' in html

    def test_inconclusive_banner_and_latency_dashes(self) -> None:
        # 4 passing samples: the functional bar clears, but the median needs
        # 5 - the latency dimension is INFEASIBLE and the composite
        # INCONCLUSIVE, with no observed percentiles to show.
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
            latency=LatencyBar(bounds=(LatencyBound("p50", 60_000),)),
        )
        result = execute(contract, RunPlan(samples=4, inputs=("a",), kind=RunKind.TEST))
        record = parse_verdict_record(render_verdict_record(result))
        html = render_test_report([record])
        assert record.verdict == "INCONCLUSIVE"
        assert "banner-inconclusive" in html and "basel test" in html
        assert '<td class="latency-observed">-</td>' in html

    def test_failing_record_renders_postcondition_failures(self) -> None:
        record = run_record(passing=False)
        html = render_test_report([record])
        assert record.verdict == "FAIL"
        assert "Postcondition Failures" in html and 'class="basel-fail"' in html

    def test_directory_sweep_skips_unparseable_files_by_name(self, tmp_path: Path) -> None:
        contract = ServiceContract(
            contract_id="svc",
            invoke=lambda v: "ok",
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("a",), kind=RunKind.TEST))
        write_verdict_record(result, tmp_path)
        (tmp_path / "junk.xml").write_text("<not-a-record>", encoding="utf-8")
        sweep = read_verdict_directory(tmp_path)
        assert len(sweep.records) == 1
        assert sweep.skipped == ("junk.xml",)


RISK_DRIVEN_DESIGN = RunDesign(
    approach="confidence-first (risk-driven)",
    claims=(
        ClaimDisclosure(
            criterion="c",
            baseline_rate=0.9,
            tolerated_rate=0.84,
            confidence=0.95,
            target_power=0.8,
            required_n=214,
        ),
    ),
    governing="c",
    baseline=BaselineDisclosure(
        source_file="svc-abc.yaml",
        generated_at="2026-07-12T10:00:00+00:00",
        samples=1000,
        baseline_rate=0.9,
        derived_threshold=0.85,
    ),
)


class TestRunDesignDisclosures:
    def test_approach_and_paired_downsizing_disclosures_render(self) -> None:
        disclosure = SizingDisclosure(
            design=RISK_DRIVEN_DESIGN,
            executed_samples=100,
            target_power=0.8,
            detectable_rate=0.769353,
            baseline_samples=1000,
            time_saved_fraction=0.9,
            time_saved_ms=12_300,
        )
        html = render_test_report([run_record()], [disclosure])
        assert "Run design" in html
        assert "confidence-first (risk-driven)" in html
        assert "tolerated rate 84%, confidence 95%, target power 80%, computed n 214" in html
        assert "(set the run size)" in html
        assert (
            "With 100 samples, this test would only catch a drop below 77% "
            "four times out of five." in html
        )
        assert "about 90% less execution time" in html
        assert "roughly 12.3 seconds" in html
        assert "Estimates only" in html

    def test_no_downsizing_disclosure_without_a_detectable_rate(self) -> None:
        disclosure = SizingDisclosure(
            design=RISK_DRIVEN_DESIGN,
            executed_samples=1000,
            target_power=0.8,
        )
        html = render_test_report([run_record()], [disclosure])
        assert "Run design" in html
        assert "only catch a drop below" not in html
        assert "less execution time" not in html

    def test_records_without_a_design_render_no_design_block(self) -> None:
        html = render_test_report([run_record()], [None])
        assert "Run design" not in html
        assert render_test_report([run_record()]).count("Run design") == 0


class TestExplorationReport:
    def test_leaderboard_ranks_by_rate_then_median(self, tmp_path: Path) -> None:
        write_variant(tmp_path, "fast", rate=1.0, successes=5, p50=100, avg=110)
        write_variant(tmp_path, "slow", rate=1.0, successes=5, p50=500, avg=510)
        write_variant(tmp_path, "flaky", rate=0.4, successes=2, p50=50, avg=60)
        sweep = read_exploration_directory(tmp_path)
        html = render_exploration_report(list(sweep.contracts))
        assert html.index("model=fast") < html.index("model=slow") < html.index("model=flaky")
        assert "Leaderboard" in html and "Per-criterion comparison" in html
        assert "Latency distribution" in html and "latency-strip-svg" in html
        assert "<script" not in html

    def test_near_tie_shares_a_rank_with_the_legend(self, tmp_path: Path) -> None:
        write_variant(tmp_path, "a", rate=1.0, successes=5, p50=100, avg=100)
        write_variant(tmp_path, "b", rate=1.0, successes=5, p50=102, avg=100)
        sweep = read_exploration_directory(tmp_path)
        html = render_exploration_report(list(sweep.contracts))
        assert 'class="tie-mark"' in html and "too close to call" in html

    def test_pass_rate_difference_is_never_a_near_tie(self, tmp_path: Path) -> None:
        write_variant(tmp_path, "a", rate=1.0, successes=5, p50=100, avg=100)
        write_variant(tmp_path, "b", rate=0.8, successes=4, p50=101, avg=100)
        sweep = read_exploration_directory(tmp_path)
        html = render_exploration_report(list(sweep.contracts))
        assert 'class="tie-mark"' not in html

    def test_below_minimum_percentile_renders_as_dash(self, tmp_path: Path) -> None:
        # 2 passing samples: below the median's minimum, so the artefact
        # carries no p50Ms and the leaderboard shows a dash.
        write_variant(tmp_path, "sparse", rate=0.4, successes=2, p50=100, avg=100)
        text_path = tmp_path / "svc" / "model-sparse.yaml"
        text = "\n".join(line for line in text_path.read_text().splitlines() if "p50Ms" not in line)
        text_path.write_text(text + "\n", encoding="utf-8")
        sweep = read_exploration_directory(tmp_path)
        html = render_exploration_report(list(sweep.contracts))
        assert '<span class="muted">-</span>' in html

    def test_constant_configuration_shows_in_details_not_labels(self, tmp_path: Path) -> None:
        # Artefacts carry the full configuration; only the differing keys
        # label the variants — the constants sit in the factor list.
        for model, p50 in (("a", 100), ("b", 300)):
            write_variant(tmp_path, model, rate=1.0, successes=5, p50=p50, avg=p50)
            path = tmp_path / "svc" / f"model-{model}.yaml"
            text = path.read_text(encoding="utf-8").replace(
                'factors:\n  "model": "' + model + '"',
                'factors:\n  "system-prompt": "You are terse."\n'
                '  "model": "' + model + '"\n  "temperature": 0.2',
            )
            path.write_text(text, encoding="utf-8")
        sweep = read_exploration_directory(tmp_path)
        labels = [v.label for v in sweep.contracts[0].variants]
        assert labels == ["model=a", "model=b"]  # constants absent from labels
        html = render_exploration_report(list(sweep.contracts))
        assert "You are terse." in html and "temperature" in html  # ...but in the details

    def test_empty_state_renders_a_friendly_paragraph(self) -> None:
        html = render_exploration_report([])
        assert "No explorations found" in html
