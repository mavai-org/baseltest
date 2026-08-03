# Vendored interchange schemas

Pinned copies of the family's interchange schemas, published by
[mavai-R](https://github.com/mavai-org/mavai-R) and consumed here by the
emitter-conformance suites. Every artefact this package writes is validated
against the copy beside it, so the emitter and the schema agree in this
repository's own test run rather than at integration time in a consumer.

**Vendored from mavai-R `0.10.8`.** Verified byte-identical to that release
when recorded (2026-08-03). The schemas are unchanged between 0.10.7 and
0.10.8 — that release corrected a worked example, not a schema — so the
recorded version names the release these copies match, not the release they
were first taken from.

| file | validated by |
|---|---|
| `mavai-explore-1.schema.json` | `tests/exploration/test_interchange_conformance.py` |
| `mavai-optimize-1.schema.json` | `tests/exploration/test_interchange_conformance.py` |
| `mavai-baseline-1.schema.json` | `tests/baseline/test_interchange_conformance.py` |
| `verdict-1.4.xsd` | the verdict emitter's suite |

## Why the version is written down

A vendored copy with no stated provenance cannot be told apart from a stale
one: the files carry no version of their own, so nothing in the tree reveals
which release they came from or whether the family has moved since. That is
the same published-but-unverifiable gap the conformance manifests exist to
close on the fixture side, and it is closed here by stating the version and
the date it was checked.

## Re-vendoring

Copy the files from a mavai-R checkout at the intended release, update the
version above and the date, then run the suites named in the table. A schema
change that the emitter does not satisfy is the point of the exercise — it
should fail here, loudly, in this repository, and not in a consumer.

Authority is the orchestrator's requirements catalog
(`inventory/catalog/interchange/`); mavai-R is the publication channel, not
the specification. When the two disagree, the catalog is right.
