# Vendored conformance fixtures

These JSON files are a pinned copy of the `mavai-R` statistical oracle's
published conformance cases (`mavai-R/inst/cases/*.json` upstream), used by
`tests/statistics/test_conformance.py` to validate this package's statistics
primitives against the reference implementation.

Pinned at `mavai-R` `v0.10.13`.

Four suites changed from the previous `v0.8.5` pin — `threshold_derivation`,
`regression_decision`, `risk_driven_sizing`, and the manifest. Every other
vendored file is byte-identical, which is why the pin sat still for so long:
the cases genuinely had not moved. The manifest had, though only in one
field — it declared `fixtureVersion 0.8.5` for five releases because nobody
regenerated it, so a consumer checking the version it claimed was reading a
stale number. `v0.10.13` fixes that alongside the new cases.

What `v0.10.13` adds is the **zero baseline**, which no fixture in the family
had ever exercised: a baseline that observed no successes, carried through a
threshold, a verdict, and a sizing calculation. `risk_driven_sizing` also
gains `sizing_gate` on every case (`ADMIT` / `REFUSE`) and `refusal_category`
on the four refused ones — both binding, so the coverage diff demands them.

A note for whoever bumps this next. The oracle's zero-baseline cases pick
their test sizes to sit where the *reference* implementation left a
floating-point residue (n = 50, 200 at 95%; n = 85 at 99%). Those sizes
cancel cleanly here, because this package computes the bound through
`statsmodels.proportion_confint` rather than the formula directly — so these
fixtures passed while the same defect was present at 178 *other*
`(n, confidence)` pairs. Residue sites are implementation-specific. The
guard that actually holds this boundary is the dense sweep in
`tests/statistics/test_wilson.py`, not the conformance suite.

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
- `risk_driven_sizing.json` (self-consistent power against the moving
  acceptance floor: required sample size, power at a candidate size, and
  the detectable-rate inversion)
- `manifest.json` (the oracle's conformance manifest: case rosters,
  binding/informational field classification, content hashes, and the
  family-mandatory suite tier)

To refresh: copy the updated files from `mavai-R/inst/cases/` after bumping
the `mavai-R` submodule, and update the pin recorded above.
