"""An oversized integer in a response is degenerate service output, not a defect.

A stochastic service can emit a syntactically valid but enormous integer the
platform will not realise as a Python ``int``. That is the service producing an
unusable value — an ordinary transform/no-value FAIL the methodology exists to
count against the configuration's pass rate — never a defect, and never an
abort. The stock ``json`` view's broad ``ValueError`` catch already secures
this; this test pins it.
"""

from pathlib import Path

import pytest

from baseltest.declarative import binding, run
from baseltest.declarative._registry import clear_registries


@pytest.fixture(autouse=True)
def fresh_registries():  # type: ignore[no-untyped-def]
    clear_registries()
    yield
    clear_registries()


def test_oversized_integer_through_the_stock_json_view_fails_the_trial_without_aborting(
    tmp_path: Path,
) -> None:
    # A ~5,000-digit integer: valid JSON, but the platform will not realise
    # it. Through the STOCK json view every trial fails, and the run completes
    # to a recorded result rather than aborting.
    huge_integer_json = '{"n": ' + "9" * 5000 + "}"

    @binding("bulk-svc")
    def invoke(value: str) -> str:
        return huge_integer_json

    contract = """
format: mavai-contract/1
contract: bulk
service: bulk-svc
transforms:
  parsed: json
criteria:
  - name: has-n
    threshold: 0.5
    postconditions:
      - in: parsed
        path: "$.n"
        matches: "^[0-9]+$"
inputs: ["a"]
"""
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    result = run(path, mode="measure", samples=8, baseline_dir=tmp_path / "b", emit=False)
    # The run completed — not aborted — with every trial a transform/no-value
    # failure.
    tally = result.criterion_results[0].tally
    assert tally.trials == 8
    assert tally.successes == 0
    assert all(reason.startswith("transform failed") for reason in tally.failure_reasons)
