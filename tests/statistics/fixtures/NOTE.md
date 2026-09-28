# Vendored conformance fixtures

These JSON files are a pinned copy of the `mavai-R` statistical oracle's
published conformance cases (the `cases-vX.Y.Z.zip` release asset,
upstream `mavai-R/inst/cases/*.json`), used by
`tests/statistics/test_conformance.py` to validate this package against the
reference implementation.

Pinned at `mavai-R` **`v0.11.1`**: Statistical Companion 1.5.0, methodology
1.5.0, fixture schema 2. Every vendored file is byte-identical to the
release asset; the manifest's content hashes are checked by every run.
`v0.11.1` changes only the manifest's `fixtureVersion` (its release is a
verdict-schema fix); every case file is as in `v0.11.0`.

`v0.11.0` replaces the decision rules, so nearly every suite changed from
the previous `v0.10.13` pin. Each suite and case now names the versioned
rule it encodes (`decisionRules`, `decisionRule`) and the methodology it
implements (`methodologyVersion`); the conformance run checks both against
what this package implements, reading the version from the manifest rather
than stating it:

- `regression/fisher` (the one-sided Fisher exact test as an integer
  cutoff) replaces the Wilson-bound regression cutoff;
- `compliance/exact-binomial` (the smallest passing count `k_min`) replaces
  the Wilson compliance clearance and the Wilson feasibility gate;
- `latency/precedence` (the precedence rank, decided on the actual number of
  successful latencies) replaces the order-statistic confidence bound;
- `latency/compliance-exact-binomial` decides explicit latency requirements.

Refused configurations carry `configuration_error` as an ordered list
(`TEST_LARGER_THAN_BASELINE`, then `COMPLIANCE_INFEASIBLE`), evaluated here
through the engine's preflight. Several suites carry exact-boundary cases —
a probability equal to alpha exactly — which only an implementation of the
exact-boundary convention (a guard band, then exact rational recomputation)
passes.

The coverage obligation is the manifest's family-mandatory tier plus the
committed `SCOPE.json` beside these fixtures (extend-only; see
`../conformance.py`). Manifest suites outside both tiers — the
informational ones — are printed as unaddressed by every conformance run.
Withdrawn with the 1.4.1 rules and no longer vendored:
`latency_threshold_bootstrap`.

Vendored here:

- family-mandatory: `wilson_ci.json`, `wilson_lower.json`,
  `regression_decision.json`, `compliance_decision.json`,
  `latency_threshold.json`, `feasibility.json`, `power_analysis.json`,
  `verdict.json`
- in scope (`SCOPE.json`): `threshold_derivation.json` (the cutoff and the
  threshold-first inversion), `risk_driven_sizing.json` (design and resolved
  sizing), `latency_percentile.json`, `latency_percentile_minimums.json`
  (also locks the artefact writers' per-percentile emission gate),
  `latency_compliance_decision.json`
- `manifest.json` (case rosters, binding/informational field
  classification, content hashes, the family-mandatory tier, the
  methodology version and the decision rules)

To refresh: download the `cases-vX.Y.Z.zip` asset of the new `mavai-R`
release, copy the files listed above, and update the pin recorded here.
