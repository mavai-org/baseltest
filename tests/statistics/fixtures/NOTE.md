# Vendored conformance fixtures

These JSON files are a pinned copy of the `mavai-R` statistical oracle's
published conformance cases (`mavai-R/inst/cases/*.json` upstream), used by
`tests/statistics/test_conformance.py` to validate this package's statistics
primitives against the reference implementation.

Pinned at `mavai-R` `v0.8.2` (local checkout at the time of vendoring:
`v0.8.2-6-ge4a3ec5`).

Only the files relevant to the proportion/threshold/verdict statistics in
`baseltest.statistics` are vendored here:

- `wilson_ci.json`
- `wilson_lower.json`
- `threshold_derivation.json`
- `power_analysis.json`
- `feasibility.json`
- `verdict.json`

To refresh: copy the updated files from `mavai-R/inst/cases/` after bumping
the `mavai-R` submodule, and update the pin recorded above.
