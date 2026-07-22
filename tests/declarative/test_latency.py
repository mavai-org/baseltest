"""The contract file's latency block: parsing, resolution, and the exit-code contract."""

from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative._cli import main
from baseltest.declarative._parser import parse_contract
from baseltest.engine import minimum_contributing_samples

BASE = """
format: mavai-contract/1
contract: paced
service: svc
criteria:
  - threshold: 0.5
    contains: "ok"
inputs: ["a"]
"""


class TestParsing:
    def test_explicit_ceilings_parse_in_percentile_order(self) -> None:
        declaration = parse_contract(BASE + "latency:\n  p50: 40\n  p95: 90\n")
        assert declaration.latency is not None
        assert declaration.latency.ceilings == (("p50", 40), ("p95", 90))
        assert declaration.latency.empirical == ()

    def test_empirical_percentiles_parse_sorted(self) -> None:
        declaration = parse_contract(BASE + "latency:\n  empirical: [p95, p50]\n")
        assert declaration.latency is not None
        assert declaration.latency.empirical == ("p50", "p95")

    def test_provenance_and_confidence_carry_through(self) -> None:
        declaration = parse_contract(
            BASE
            + "latency:\n  p95: 500\n  confidence: 0.9\n  threshold-origin: sla\n"
            + '  contract-ref: "Acme SLA v3 §4.2"\n'
        )
        assert declaration.latency is not None
        assert declaration.latency.confidence == 0.9
        assert declaration.latency.threshold_origin == "sla"
        assert declaration.latency.contract_ref == "Acme SLA v3 §4.2"

    @pytest.mark.parametrize(
        ("block", "match"),
        [
            ("latency:\n  p95: 500\n  empirical: [p99]\n", "contradictory"),
            ("latency:\n  p50: 900\n  p95: 500\n", "non-decreasing"),
            ("latency:\n  confidence: 0.9\n", "declares no bounds"),
            ("latency:\n  p95: 0\n", "positive whole number"),
            ("latency:\n  p95: 12.5\n", "positive whole number"),
            ("latency:\n  p97: 500\n", "unknown key"),
            ("latency:\n  empirical: [p97]\n", "unknown percentile"),
            ("latency:\n  empirical: [p95, p95]\n", "at most once"),
            ("latency:\n  empirical: []\n", "non-empty list"),
        ],
    )
    def test_malformed_blocks_are_refused_at_load(self, block: str, match: str) -> None:
        from baseltest.declarative._errors import ContractConfigurationError

        with pytest.raises(ContractConfigurationError, match=match):
            parse_contract(BASE + block)


def write_files(tmp_path: Path, latency_block: str) -> Path:
    (tmp_path / "mavai-bindings.py").write_text(
        "import itertools\n"
        "import time\n"
        "from baseltest.declarative import Bindings\n"
        "bindings = Bindings()\n"
        "_counter = itertools.count()\n"
        "@bindings.binding('svc')\n"
        "def invoke(value: str) -> str:\n"
        "    time.sleep(0.003)\n"
        "    return 'ok' if next(_counter) % 10 < 9 else 'nope'\n",
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(BASE + latency_block, encoding="utf-8")
    return contract


class TestExitCodeContract:
    def test_generous_ceilings_pass(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_files(tmp_path, "latency:\n  p50: 60000\n")
        assert main(["test", str(contract), "--samples", "10"]) == 0

    def test_breached_ceiling_fails_the_test(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.chdir(tmp_path)
        # The binding sleeps 3ms per invocation; a 1ms median ceiling breaches.
        contract = write_files(tmp_path, "latency:\n  p50: 1\n")
        assert main(["test", str(contract), "--samples", "10"]) == 1

    def test_percentile_unsupported_by_planned_n_is_refused(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_files(tmp_path, "latency:\n  p99: 60000\n")
        assert main(["test", str(contract), "--samples", "10"]) == 2
        assert "needs at least 100 passing samples" in capsys.readouterr().err

    def test_empirical_without_baseline_is_refused(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_files(tmp_path, "latency:\n  empirical: [p50]\n")
        assert main(["test", str(contract), "--samples", "10"]) == 2
        assert "run `basel measure` first" in capsys.readouterr().err

    def test_measure_then_empirical_judges_no_worse_than_measured(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_files(tmp_path, "latency:\n  empirical: [p50]\n")
        assert main(["measure", str(contract), "--samples", "30"]) == 0
        assert main(["test", str(contract), "--samples", "10"]) == 0

    def test_saturation_at_the_requested_confidence_is_refused(
        self, tmp_path: Path, monkeypatch: Any, capsys: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # A 30-sample measure yields ~27 passing — below the 59 a
        # non-saturated 95% bound on the 95th percentile requires.
        contract = write_files(tmp_path, "latency:\n  empirical: [p95]\n")
        assert main(["measure", str(contract), "--samples", "30"]) == 0
        assert main(["test", str(contract), "--samples", "25"]) == 2
        assert "at least 59 are needed" in capsys.readouterr().err

    def test_too_few_passing_samples_is_unsupportable_not_a_verdict(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "mavai-bindings.py").write_text(
            "import itertools\n"
            "from baseltest.declarative import Bindings\n"
            "bindings = Bindings()\n"
            "_counter = itertools.count()\n"
            "@bindings.binding('svc')\n"
            "def invoke(value: str) -> str:\n"
            "    return 'ok' if next(_counter) % 8 < 3 else 'nope'\n",
            encoding="utf-8",
        )
        contract = tmp_path / "contract.yaml"
        contract.write_text(
            BASE.replace("threshold: 0.5", "threshold: 0.05")
            + "intent: smoke\nlatency:\n  p50: 60000\n",
            encoding="utf-8",
        )
        # 3 of 8 samples pass: the functional bar clears, but the median
        # needs 5 passing samples — no latency judgement is possible.
        assert main(["test", str(contract), "--samples", "8"]) == 3

    def test_verdict_record_carries_the_latency_element(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        contract = write_files(tmp_path, "latency:\n  p50: 60000\n")
        assert main(["test", str(contract), "--samples", "10"]) == 0
        record = next((tmp_path / "_baseltest" / "verdicts").glob("*.xml")).read_text()
        assert "<latency" in record and 'provenance="explicit"' in record

    def test_measure_ignores_the_latency_bar_and_records_the_profile(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # An impossible ceiling: a measure run must not judge it.
        contract = write_files(tmp_path, "latency:\n  p50: 1\n")
        assert main(["measure", str(contract), "--samples", "10"]) == 0
        baseline = next((tmp_path / "_baseltest" / "baselines").glob("*.yaml")).read_text()
        assert "sortedPassingLatenciesMs:" in baseline


def test_gating_table_backs_the_planned_n_refusal() -> None:
    # The refusal threshold and the emission gate are the same table.
    assert minimum_contributing_samples("p99") == 100
