"""An oversized integer in a response is degenerate service output, not a defect."""

from pathlib import Path

from baseltest.declarative import Bindings, run


def test_oversized_integer_through_the_stock_json_view_fails_the_trial_without_aborting(
    tmp_path: Path,
) -> None:
    # Well past the ~4,300-digit int-to-str conversion limit CPython enforces.
    huge_integer_json = '{"n": ' + "9" * 5000 + "}"

    bindings = Bindings()

    @bindings.binding("bulk-svc")
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
    result = run(
        path, mode="measure", samples=8, baseline_dir=tmp_path / "b", emit=False, bindings=bindings
    )
    tally = result.criterion_results[0].tally
    assert tally.trials == 8
    assert tally.successes == 0
    assert all(reason.startswith("transform failed") for reason in tally.failure_reasons)
