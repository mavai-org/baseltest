# Vendored conformance fixtures

These JSON files are a pinned copy of the `mavai-R` statistical oracle's
published conformance cases (`mavai-R/inst/cases/*.json` upstream), used by
`tests/statistics/test_conformance.py` to validate this package's statistics
primitives against the reference implementation.

Pinned at `mavai-R` `v0.8.4` (the `regression_decision` suite and the
conformance `manifest.json` are new in 0.8.4; every other vendored file
is byte-identical with 0.8.3). `test_conformance.py` verifies each
vendored suite against the manifest's content hash, so drift from the
pin fails the build rather than passing silently.

The manifest-driven coverage obligation is the oracle's family-mandatory
tier plus the committed `SCOPE.json` beside these fixtures (extend-only;
see `../conformance.py`). Manifest suites outside both tiers are printed
as unaddressed by every conformance run.

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
- `latency_threshold.json`
- `latency_threshold_bootstrap.json` (conformance fields incl. `k_raw` /
  `saturated`; the bootstrap fields are informational comparison content,
  not conformance targets — no bootstrap method is implemented)
- `regression_decision.json` (the composed decision rules — regression's
  `K >= cutoff` and compliance's Wilson-bound clearance — evaluated
  through the production verdict path)
- `manifest.json` (the oracle's conformance manifest: case rosters,
  binding/informational field classification, content hashes, and the
  family-mandatory suite tier)

To refresh: copy the updated files from `mavai-R/inst/cases/` after bumping
the `mavai-R` submodule, and update the pin recorded above.
