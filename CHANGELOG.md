# Changelog

All notable changes to `baseltest` are documented here. Entries are written
for the reader upgrading: what changed, what it means for their contracts,
and what they must do.

Versions follow semantic versioning. While on 0.x, **minor** bumps may
carry breaking changes; each says so in its first line.

## [0.19.0] — 2026-08-03

**The baseline artefact becomes the family format. Breaking: regenerate your baselines.**

baseltest now writes `mavai-baseline-1`, the single baseline format shared across the mavai family, replacing `baseltest-baseline-2`. There is no dual-read: a baseline written by an earlier version is refused, with a diagnostic naming what it found, what was expected, and the verb that regenerates it. **Re-run `basel measure` for every contract whose baseline you have committed.**

Three changes are visible in behaviour, not just in the file:

- **Resolution discriminates on the service.** A contract may exercise several services and a service may be the subject of several contracts, so neither names a baseline on its own. The service is now identity in its own right rather than something carried along as provenance, and the filename carries it — `{contract}.{service}-{inputs}.yaml`. Two services under one contract no longer share a baseline.
- **`taskFormat` no longer takes part in matching.** Identity and provenance are separate fields in the artefact now, so nothing has to be subtracted from one to recover the other. A contract-format identifier does not change the distribution being measured, so it is provenance.
- **The record is fingerprinted and verified on load.** A baseline edited by hand after it was written is refused rather than trusted.

**Each criterion states its Wilson lower bound.** A baseline has always stated what was observed; it now also states how firmly the evidence holds it — the one-sided bound over that criterion's own counts, at the confidence level the record states. It is a characterisation of the recorded evidence and never an acceptance threshold: no resolver and no threshold derivation reads it. At zero trials it is `null` rather than absent, so "no evidence" stays distinguishable from "an older artefact", and the pass rate is omitted entirely — asserting a rate from the same non-evidence that makes the bound null is exactly the confusion the null exists to flag.

**Failures say which kind they were.** Every failure now carries its axis: the postcondition was judged and did not hold, or no testable value could be produced at all. It was previously recoverable only by matching a prefix on a reason string.

**Standings show what the check actually found.** An exemplar was the whole view output, stringified and truncated — so on a document-extraction corpus every row showed the same alphabetically-first field, whichever check had failed. It is now the value at the check's own path, with a path that selects nothing marked distinctly: a missing field and a wrong extraction are different defects.

**Every emitted baseline is validated against the published schema** in baseltest's own suite, against a vendored copy of mavai-R 0.10.8. That suite found a crash on its first run and corrected a worked example in the oracle.
