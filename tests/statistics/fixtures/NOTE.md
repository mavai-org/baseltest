# Vendored conformance fixtures

These JSON files are a pinned copy of the `mavai-R` statistical oracle's
published conformance cases (`mavai-R/inst/cases/*.json` upstream), used by
`tests/statistics/test_conformance.py` to validate this package's statistics
primitives against the reference implementation.

Pinned at `mavai-R` `v0.8.3` (the `latency_percentile_minimums` suite is
new in 0.8.3; every other vendored file is byte-identical with 0.8.2).

Only the files relevant to the statistics `baseltest` implements are
vendored here:

- `wilson_ci.json`
- `wilson_lower.json`
- `threshold_derivation.json`
- `power_analysis.json`
- `feasibility.json`
- `verdict.json`
- `latency_percentile.json`
- `latency_percentile_minimums.json` (also locks the artefact writers'
  per-percentile emission gate in `baseltest.engine`)

To refresh: copy the updated files from `mavai-R/inst/cases/` after bumping
the `mavai-R` submodule, and update the pin recorded above.
