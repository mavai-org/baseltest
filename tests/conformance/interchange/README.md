# Vendored interchange schemas

Pinned copies of the family's interchange schemas, published by
[mavai-R](https://github.com/mavai-org/mavai-R) and consumed here by the
emitter-conformance suites. Every artefact this package writes is validated
against the copy beside it, so the emitter and the schema agree in this
repository's own test run rather than at integration time in a consumer.

**Vendored from mavai-R `0.11.0`**: verified byte-identical to the
`interchange-v0.11.0.zip` release asset when recorded (2026-09-28). The three
JSON schemas are unchanged from `0.10.12`; the verdict schema moves to
`verdict-1.7.xsd` (Statistical Companion 1.5.0), which names the decision
behind a verdict: the record's methodology version, the versioned decision
rule on each criterion row and strict latency evaluation, the latency
dimension's verdict, the overall test verdict, and — for a configuration
refused before any sample ran — the configuration-error list, no verdict
value and the termination reason `CONFIGURATION_REFUSED`. `verdict-1.6.xsd`
is no longer vendored: this emitter writes 1.7 only.

One schema gap is known and closed upstream in mavai-R 0.11.1: in 0.11.0
every latency evaluation requires `threshold-ms`, which a baseline-derived
constraint with no precedence rank (saturated) does not have. The emitter
already writes the 0.11.1 shape — status `SATURATED`, no `threshold-ms`, no
`baseline-rank` — rather than manufacture a threshold; such a record
validates once this copy is re-vendored from 0.11.1.

**Vendored from mavai-R `0.10.12`** (superseded): verified byte-identical to
the `interchange-v0.10.12.zip` release asset when recorded (2026-08-11). The
copies were first taken from the repository commit that introduced them,
ahead of the release, because this emitter is the first to adopt the
fields; the check against the published asset closes that gap.

A standings row gains an optional `provenance`: `criterion` for a
postcondition the criterion states, `input` for one an input's own expected
values state. `verdict-1.6.xsd` carries that attribute and adds an optional
`<inputs>` element, so a verdict record can name the document a failure came
from rather than its index alone — the block every other format already had.

**Vendored from mavai-R `0.10.11`** (superseded, recorded here because the
`inputs` block in the three JSON schemas arrived in it): verified
byte-identical to the `interchange-v0.10.11.zip` release asset when recorded
(2026-08-10).

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
| `verdict-1.7.xsd` | the verdict emitter's suite |

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
