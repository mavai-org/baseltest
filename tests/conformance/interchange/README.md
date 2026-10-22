# Vendored interchange schemas

Pinned copies of the family's interchange schemas, published by
[mavai-R](https://github.com/mavai-org/mavai-R) and consumed here by the
emitter-conformance suites. Every artefact this package writes is validated
against the copy beside it, so the emitter and the schema agree in this
repository's own test run rather than at integration time in a consumer.

**Vendored from mavai-R `0.15.0`**: `verdict-1.10.xsd` re-taken from
mavai-R commit 02f4d7a on 2026-10-22, ahead of the release; check it
against the `interchange-v0.15.0.zip` release asset once published. Only
a comment changes from `0.14.0` (a 1.10 record's methodology version is
"1.7.0" or later); no definition changes.

**Vendored from mavai-R `0.14.0`** (superseded): `verdict-1.10.xsd` added, taken from
the `v0.14.0` tag (commit 539980e) on 2026-10-22. It is additive
over 1.9, which is additive over 1.8: `DecisionRuleEnum` gains
`compliance/smoke-exact-binomial` and
`latency/smoke-compliance-exact-binomial`, the rules that decide a
requirement under smoke intent, and `@methodology-version` reads "1.7.0".
This emitter writes 1.10 and none of 1.9's optional run-control content.
`verdict-1.8.xsd` is no longer vendored, and the three JSON schemas are
unchanged.

**Vendored from mavai-R `0.13.1`** (superseded): verified byte-identical to the
`interchange-v0.13.1.zip` release asset when recorded (2026-10-19).
`mavai-optimize-1.schema.json` gains the optional `convergence.selection`: a
selecting stepper's optimum, with its evidence pooled across every iteration
that measured it, its two-sided interval and confidence, the stopping reason,
whether it was confirmed, and the finalists' standings. `bestIteration` is
re-described as the best single observation. The other two JSON schemas and
`verdict-1.8.xsd` were unchanged. `verdict-1.9.xsd` (the run-controls
amendment, additive over 1.8) was not vendored: this emitter wrote 1.8 until
it moved to 1.10.

**Vendored from mavai-R `0.12.0`** (superseded): verified byte-identical to the
`interchange-v0.12.0.zip` release asset when recorded (2026-10-07). The three
JSON schemas are unchanged; the verdict schema moves to `verdict-1.8.xsd`
(Statistical Companion 1.6.0), a clean break from 1.7 that records whether
each dimension was enforced or advisory: a required `mode` on the functional
composite and a `mode` on the latency element (`enforced` or `advisory`).
Every latency evaluation states the rule that decided it and that rule's
outcome as its status (`PASS`, `FAIL`, `INFEASIBLE` or `SATURATED`), and
carries no mode of its own; `STRICT_FAIL` is renamed `FAIL`, and
`ADVISORY_WARN`, `strict-violations` and `advisory-violations` are
withdrawn. The record's verdict composes the enforced dimensions only, and
is `PASS` when none is. `verdict-1.7.xsd` is no longer vendored: this
emitter writes 1.8 only.

**Vendored from mavai-R `0.11.2`** (superseded): verified byte-identical to the
`interchange-v0.11.2.zip` release asset when recorded (2026-09-30). The three
JSON schemas are unchanged; `verdict-1.7.xsd` gains an optional
`required-pass` on the criterion row: the smallest passing count under the
rule that decided the criterion (the Fisher cutoff for `regression/fisher`,
`k_min` for `compliance/exact-binomial`), so a reader states the bar as the
count the verdict was decided by rather than deriving it from `threshold`. It
is absent when no rule decided the criterion or no count can pass. The
emitter writes it from the count the engine decided with.

**Vendored from mavai-R `0.11.1`** (superseded): verified byte-identical to the
`interchange-v0.11.1.zip` release asset when recorded (2026-09-28). The one
change from `0.11.0` closes a gap in `verdict-1.7.xsd`: a baseline-derived
latency constraint with no precedence rank (saturated) has no threshold, so an
evaluation now takes status `SATURATED` and omits `threshold-ms` (and
`baseline-rank`). The emitter writes that shape rather than manufacture a
threshold, and the record now validates here.

**Vendored from mavai-R `0.11.0`** (superseded): verified byte-identical to the
`interchange-v0.11.0.zip` release asset when recorded (2026-09-28). The three
JSON schemas are unchanged from `0.10.12`; the verdict schema moves to
`verdict-1.7.xsd` (Statistical Companion 1.5.0), which names the decision
behind a verdict: the record's methodology version, the versioned decision
rule on each criterion row and strict latency evaluation, the latency
dimension's verdict, the overall test verdict, and — for a configuration
refused before any sample ran — the configuration-error list, no verdict
value and the termination reason `CONFIGURATION_REFUSED`. `verdict-1.6.xsd`
is no longer vendored: this emitter writes 1.7 only.

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
| `mavai-optimize-1.schema.json` | `tests/optimization/test_interchange_conformance.py` |
| `mavai-baseline-1.schema.json` | `tests/baseline/test_interchange_conformance.py` |
| `verdict-1.10.xsd` | the verdict emitter's suite |

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
