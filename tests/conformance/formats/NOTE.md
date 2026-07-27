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

Pinned at `mavai-R` **v0.10.0** — the partial-credit and default-view
amendments: `optional:`/`optional-slack:` with the structural categories
`optional-slack-malformed`/`optional-operand`/`optional-on-parses`, and the
path-conditional default subject view, which retires the structural
`path-without-in` category in favour of the semantic
`default-view-unresolvable` (its old case reworked as
`default-view-no-views.yaml`). Earlier pins: v0.9.5 (the boolean form `is:`
and its refusal category `is-operand-not-boolean`); v0.9.4 (the
value-comparison forms — the numeric sextet `eq`/`ne`/`lt`/`le`/`gt`/`ge`,
`not-equals`, `equals-ci`, `is-null`, and the collective
`equals-set`/`contains-set`/`count-equals`; v0.9.4 isolates v0.9.3's
scalar case to a single criterion after this adoption surfaced its
two-criteria-plus-per-input-`expected:` contradiction — a corpus defect,
the triage discipline's second live exercise); v0.9.2 (the max-iterations
cases isolated to their category after this adoption surfaced that
v0.9.1's two `optimization-max-iterations-*` cases refused before
reaching their category — a corpus defect).
The copy is vendored, not fetched, so the build passes offline; bump it by
replacing `manifest.yaml` and `corpus/` with the contents of the new
release's `formats-vX.Y.Z.zip` and updating this pin note.

The published JSON Schemas are deliberately not vendored: they are the
structural projection consumed by the oracle's own build; this package's
obligation is loader conformance against the corpus and manifest.
