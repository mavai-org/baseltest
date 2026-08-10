# Vendored interchange schemas

Pinned copies of the family's interchange schemas, published by
[mavai-R](https://github.com/mavai-org/mavai-R) and consumed here by the
emitter-conformance suites. Every artefact this package writes is validated
against the copy beside it, so the emitter and the schema agree in this
repository's own test run rather than at integration time in a consumer.

**Vendored from mavai-R `0.10.11`.** Verified byte-identical to the
`interchange-v0.10.11.zip` release asset when recorded (2026-08-10). All
three JSON schemas changed in it: each gained an optional `inputs` block
stating how every input a run drove presents itself, so an artefact can name
an input that behaved and not only one that failed.

Two corrections to what this file used to say. The `0.10.10` note claimed all
three schemas were byte-identical to that release; `mavai-baseline-1` was
never in that asset at all — it had been absent from the interchange bundle
since it was introduced, and the copy here came from the repository. Fixed
upstream in mavai-R 0.10.11, which also refuses to publish a bundle missing a
schema. And the verdict copy is `1.5`, not the `1.4` the prose claimed.

| file | validated by |
|---|---|
| `mavai-explore-1.schema.json` | `tests/exploration/test_interchange_conformance.py` |
| `mavai-optimize-1.schema.json` | `tests/exploration/test_interchange_conformance.py` |
| `mavai-baseline-1.schema.json` | `tests/baseline/test_interchange_conformance.py` |
| `verdict-1.5.xsd` | the verdict emitter's suite |

## Why the version is written down

A vendored copy with no stated provenance cannot be told apart from a stale
one: the files carry no version of their own, so nothing in the tree reveals
which release they came from or whether the family has moved since. That is
the same published-but-unverifiable gap the conformance manifests exist to
close on the fixture side, and it is closed here by stating the version and
the date it was checked.

## Re-vendoring

Take the files from the release's `interchange-*.zip` asset — not from a
mavai-R checkout, so the copies are what consumers actually receive — update
the version above and the date, then run the suites named in the table. A schema
change that the emitter does not satisfy is the point of the exercise — it
should fail here, loudly, in this repository, and not in a consumer.

Authority is the orchestrator's requirements catalog
(`inventory/catalog/interchange/`); mavai-R is the publication channel, not
the specification. When the two disagree, the catalog is right.
