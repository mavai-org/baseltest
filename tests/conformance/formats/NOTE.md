# Vendored format conformance corpus

This directory is a pinned copy of the mavai family's declarative format
conformance corpus, published by the `mavai-R` repository as the
`formats-vX.Y.Z.zip` release asset (upstream: `mavai-R/inst/formats/`,
`manifest.yaml` plus `corpus/`). `tests/conformance/test_format_conformance.py`
drives this package's contract-file and services-file loaders over every
corpus case and asserts the manifest's binding obligations: the outcome
(loads / refused) and, for refusals, the category. Refusal message wording is
informational — the mapping from each category to this package's own message
is maintained in the test.

Pinned at `mavai-R` **v0.9.1** (the first release carrying the formats
asset), with one correction applied ahead of the next release: the two
`optimization-max-iterations-*` cases carry upstream `mavai-R` commit
`18dffe5` (this adoption surfaced that they refused before reaching their
category — a corpus defect; the fix isolates each case to its one defect).
Re-pin cleanly at the next tagged release. The copy is vendored, not
fetched, so the build passes offline; bump it by replacing `manifest.yaml`
and `corpus/` with the contents of the new release's `formats-vX.Y.Z.zip`
and updating this pin note.

The published JSON Schemas are deliberately not vendored: they are the
structural projection consumed by the oracle's own build; this package's
obligation is loader conformance against the corpus and manifest.
