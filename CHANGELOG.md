# Changelog

All notable changes to `baseltest` are documented here. Entries are written
for the reader upgrading: what changed, what it means for their contracts,
and what they must do.

Versions follow semantic versioning. While on 0.x, **minor** bumps may
carry breaking changes; each says so in its first line.

## [0.22.1] — 2026-08-10

**A postcondition now says who stated it, and a verdict record says what
its inputs are.** Both are additive: nothing in your contracts changes, and
every artefact keeps the shape it had plus one more fact.

A standings row states `provenance`: `criterion` for a postcondition the
criterion states, asserted of every input; `input` for one an input's own
`expected:` block states, asserted only against that input. Both are
postconditions — they differ in who stated them, and their denominators
differ accordingly, an input's reaching only the samples that input drove.
A consumer that could not tell them apart listed one figure out of six
beside another out of twelve with nothing to explain the difference; the
family's report now separates them because the artefact finally says so.
Stated on every row, not only the input ones: a consumer reading absence
as `criterion` is reading a default, and a default is worth less than a
fact when the two kinds sit in one list.

The fact is a carry, not a computation. The evaluator already tags an
input's expectation with the index it dispatches on
(`Postcondition.applies_to_input`), and that tag is the same fact under
another name.

Verdict records move to **1.6** and gain an `<inputs>` element: one entry
per input the run drove, its index and a bounded excerpt. Every other
interchange format has carried this for some time; a verdict record could
not, so a verdict report named the document a failure came from by its
index and nothing else. Every input is named, not only the ones a failure
came from. The vendored schemas move to mavai-R 0.10.12 — ahead of its
release, since this emitter is the first to adopt the fields; the
conformance README says so rather than claiming an asset it was not taken
from.

## [0.22.0] — 2026-08-10

**Breaking: this package renders no HTML, and `baseltest.reporting.render_test_report`
is gone.** In exchange, installing it installs the renderer that draws the
reports instead, so what used to be two installations is one.

Reports were rendered in two places: `basel test --html-report` drew its own
page in Python, while exploration comparisons had already moved to
[mavai](https://github.com/mavai-org/mavai/releases), the family's shared
renderer. Two renderers meant two answers to the same question, drifting
apart, and punit and feotest each carried a third and a fourth. There is now
one, and this framework's half of the split is what it was always meant to
be: emitting the canonical artefacts.

**`--html-report PATH` now works on every verb that writes artefacts** —
`test`, `measure`, `explore` and `optimize` — and each hands its run's
artefacts to mavai, which the platform wheels carry:

```console
$ basel explore contract.yaml --html-report comparison.html
$ basel test contract.yaml --samples 200 --html-report verdict.html
```

Rendering separately still works exactly as before, and produces the same
page, because it is the same renderer over the same artefacts:

```console
$ basel test contract.yaml --samples 200
$ mavai verdict _baseltest -o verdict.html
```

The flag is **refused before the run** when it cannot be honoured — mavai
not on `PATH`, or `--no-verdict-xml` suppressing the very record the report
draws from — so a run never costs samples for a report that was never going
to appear. It **never changes the verb's exit code**: a passing run whose
report failed to draw is still a passing run, and the failure is loud on
stderr.

**Installing baseltest installs the renderer it delegates to.**

The previous change made every report mavai's to draw. That was right for
the reports and wrong for the reader, who now installed a framework that
could run an experiment and not show it until they had separately found,
downloaded and unpacked a second tool — for a binary whose only purpose is
to draw what baseltest just wrote.

`pip install baseltest` now brings it. Each supported platform gets a wheel
carrying that platform's renderer, installed as `mavai` in the environment's
scripts directory, so it is on your path for direct use:

```console
$ pip install baseltest
$ mavai explore _baseltest/explorations -o comparison.html   # no framework involved
```

`basel --version` names the renderer this installation would use — the one
it carries, one it found on `PATH`, or none. It prints on stderr, leaving
the version string on stdout byte-identical to the `generator` a verdict
record carries, which is what makes the two comparable.

`MAVAI_BIN` names a renderer to use instead: the escape hatch for a local
build. A stated override that does not resolve is refused rather than
quietly replaced by a different renderer.

**`basel report` draws the page without running the experiment again.**

Every verb that writes artefacts has two stages: producing them, which
costs samples and touches a service, and drawing them, which costs nothing
and touches nothing. `--html-report` does both at once. This does the
second alone, over what a previous run already wrote:

```console
$ basel explore contract.yaml            # yesterday, no report asked for
$ basel report explore -o comparison.html
```

The verb names the stage and its first argument names the kind, so the four
kinds baseltest runs are the four it reports on — `test`, `measure`,
`explore`, `optimize`. With no `-o`, the report goes to stdout, so it pipes
like everything else here.

**Asking later gives exactly what asking during the run would have.**
`basel <kind> <contract> --html-report R` and `basel <kind> <contract>`
followed by `basel report <kind> -o R` produce the same bytes: it is the
same renderer over the same artefacts.

A contract narrows the report to that contract's artefacts, for the kinds
written one directory per contract — `explore` and `optimize`. Verdicts and
baselines are written one file per run, carrying the contract in the
filename, and no reader here selects artefacts by parsing a filename; so a
contract given to `basel report test` or `basel report measure` is
**refused**, naming why, rather than silently reporting on everything.

Asking for a report of something never written names the directory it
looked in and the run that would fill it, which is a different answer from
a report that failed to draw. And unlike the flag on a run, this verb's
exit code *is* the report's: drawing it is what it was asked to do.

**Fixed: `basel explore --html-report` produced no report at all.** It handed
the renderer the explorations root, and mavai reads documents exactly two
directories down. An exploration writes one level deeper than every other
kind — `explorations/<contract>/<swept keys>/*.yaml`, because its grid is
grouped by the keys it sweeps — so the root had directories beneath it and
nothing renderable beneath those. Every exploration report since the
delegation landed was empty. The other three kinds were checked rather than
assumed and already sat at the right depth.

**An artefact says what its inputs are.** Each descriptive artefact now
states an `inputs` block: one entry per input the run drove, carrying the
`inputIndex` failure entries already use and a bounded excerpt. Before it,
an excerpt rode on failure entries alone, so an input that behaved had
nowhere to say what it was and a report named one row and left the rest
blank — which reads as missing data rather than as a fact about which inputs
failed. Optional in the format (mavai-R 0.10.11), so an older document is
unaffected, and a consumer that has not adopted it renders as it did.

**A file input says its name, not its repr.** Every run whose failing input
came from a file used to publish
`FileInput(path=PosixPath('/home/you/corpus/note.pdf'), kind=…, content_hash=…)`
as its excerpt — a Python spelling in a document punit and feotest also
write, carrying the authoring machine's absolute path into a file meant to
be published and read elsewhere. It presents as the document's name now.
Dropping the path costs no identity, which is why it is safe: identity has
always been the content hash and never the path.

**What changed for you**

- **Re-run `basel explore … --html-report` if it has been producing nothing.**
  Every exploration report since the delegation landed was empty, and nothing
  about your contract was wrong.
- **Nothing, if you already had `mavai` on your `PATH`.** An installation's
  own renderer is preferred, but PATH still answers where there is none.
- `--html-report` on `test` produces mavai's verdict report, not the page
  baseltest used to draw. **The run-design and sizing-transparency block is
  not in it** — the approach, the risk-driven claims, and the disclosed
  detectable rate and time saved. The verdict record still *records* the
  declared design; no renderer reads it yet. Restoring it is tracked as a
  family-level follow-up and needs the computed disclosures to travel in the
  artefact, since mavai computes nothing.
- `--html-report` is **no longer refused on `measure`**, and on `explore` it
  **no longer refuses with a pointer** to run mavai yourself; it runs it.
- **Removed:** `baseltest.reporting.render_test_report` and the
  `reporting.report_html` / `reporting.test_report` modules.
- On a platform with no published wheel, or installing from source, you get
  the pure wheel: a complete framework that runs experiments and writes
  artefacts, and refuses a report request before the run with a message
  naming both ways to fix it. Nothing renders differently; there is simply
  nothing to render with.
- Artefacts written by this release carry one more block. Nothing reads it as
  identity, and a reader that does not know it ignores it.
- Reports are drawn by **mavai 0.17.0 or later**, which the platform wheels
  carry and whose version `basel --version` states. It is pinned at build
  time and does not float between releases.

## [0.21.0] — 2026-08-09

**A failed delivery says so.** Additive to every artefact this package
writes; needs mavai-R 0.10.10 or later to validate. **Verdict records move
to `verdict-1.5`.**

A trial that never received a response and a trial that received one and
failed it are opposite findings, and the artefacts stated them identically.
Both were a failed trial, both a `failureDistribution` entry, and the
delivery cause travelled as free text in the same `condition` field a
declared contract condition uses — often carrying an endpoint, which the
family's key discipline forbids in an identity. So a run in which nothing
was ever measured presented exactly like a run in which everything was
measured and found wanting: four configurations at `0.000`, diagnosable
only by reading raw YAML.

Every failure entry now states **`kind`** — `delivery` or `evaluated` — and
a delivery entry's `condition` is its **cause**, from a closed vocabulary:
`unreachable`, `client-deadline`, `peer-timeout`, `server-error`,
`unusable-response`. `client-deadline` says *baseltest stopped waiting*,
which it may now say because it has a deadline of its own (below);
`peer-timeout` says the peer stated that it did — an HTTP 504, and not the
same fact however similar the elapsed seconds look.

The arithmetic is untouched. An undelivered trial is still one failed trial
counted against every criterion, and the entries still sum to `failures`.
There is deliberately no separate count of delivery failures: summing the
delivery-kind entries is a trivial aggregate over stated counts, where a
second field would be a second source of one truth.

**The verdict record states its failure attribution at all.** It never
had a `functional` element: a test run stated per-criterion outcomes and
postcondition clauses, and nothing that said what the run as a whole failed
on. It now states `functional` with the run's attribution — one `check` per
bounded identity, with its `kind` — so a test against a service that never
answered reads as one, instead of as a `FAIL` on every criterion at a rate
of zero.

The attribution is **per trial**, computed in the sampling fold rather than
summed from the per-criterion tallies. A trial that fails two criteria
appears in both of those tallies, and an undelivered trial fails every one
of them, so summing would multiply a single incident by the width of the
contract — the same defect, in a new place, that the explore leaderboard's
`no result for 19/200` was. The counts sum to the run's stated failures.

`ServiceDeliveryError` gains an optional `cause`. An author raising it from
their own binding may leave it unstated — the framework knows nothing about
that transport and never guesses which cause a message describes; the entry
then states the kind and no cause. In the baseline artefact `kind` sits
beside the existing `reason`, and a delivery entry states no `reason` at
all: that field is the companion's axis over trials that *were* evaluated.

**baseltest now gives up.** Breaking for every existing baseline: re-run
`basel measure`.

Until now this package invoked a service with no deadline at all.
Python's `urlopen` defaults to waiting forever, nothing here overrode it,
and there was no flag, key, or environment variable that could. A run was
observed blocked for 94 minutes on 0.9 seconds of CPU, every sample
waiting on the HTTP status line of a peer that had accepted the request
and then gone silent. Nothing failed and nothing warned, because from the
framework's point of view nothing had happened yet.

The `language-model` service now takes `deadline-ms:` — how long baseltest
waits for one response before recording a failed delivery. It bounds the
whole exchange rather than the connection, which is what the observed
failure requires: the connection succeeded. Unstated, it resolves to
`600000` (ten minutes) and is **recorded as resolved**, because a default
nobody can see is the hidden constant this key exists to abolish. Ten
minutes is far above what a non-streaming completion at the token ceiling
takes on the slowest configurations in use, so it manufactures no
failures; state a smaller one where less patience is the point.

The deadline is **identity**. A shorter deadline converts slow-but-delivered
responses into failed deliveries, so two runs at different deadlines are
not measuring the same thing and a baseline taken under one does not
resolve a test run under another. This is why every existing baseline
drifts on upgrade: it was measured under no deadline at all, which is not
the same population as ten minutes. `basel test` says so, naming
`deadlineMs` as the differing key; `basel measure` writes a current one.

A timed-out sample is a **failed delivery**, counted like any other — one
failed sample, every postcondition skipped, the run completing to a
verdict. It is never retried: a re-attempted sample is a resampled trial
and would bias the observed rate.

**The baseline states its standings in the family's shape.** Breaking for
anything that reads a baseline artefact's standings block.

`mavai-baseline-1` defines the standings block once, as the exploration and
optimization artefacts already state it: a `standings:` mapping carrying the
declared `optionalSlack` and a `rows:` list, one row per (input, check).
This package kept emitting the earlier `postconditionStandings:` shape — a
mapping of input index to check to tally — so a baseline it wrote was a
dialect of the format it claimed, and the family's report renderer, reading
the format as specified, drew no standings for a baseltest run at all.

The block now takes the family shape. Each row is one JSON object per line,
which is a YAML flow mapping in any parser and a single scalar line for this
package's own reader, so nothing changed about how a baseline reads back.
The declared budget moves inside the block, beside the rows it governs.

Baselines written by earlier versions are not read by this one — the format
was a clean break already. Re-run `basel measure` to write current
artefacts.

**`basel` can state its own version.**

`basel --version` prints `baseltest <version>` and exits 0, with no verb and
no contract file:

```console
$ basel --version
baseltest 0.20.0
```

Previously it printed a usage error and exited 2, because `--version` is not
one of the verbs the root parser requires. A checkout can disagree with
itself about which build is installed — a version pinned in `pyproject.toml`,
another resolved in `uv.lock`, a third actually present in the virtualenv —
and answering that question meant reading the lock file by hand. Now the tool
answers it.

The string names the distribution, not the command, and is the same string
the verdict record carries in its `generator` attribute. A reader holding an
artefact and a `basel` on their path can compare the two directly and see
whether that build wrote it.

## [0.20.0] — 2026-08-05

**An author can name a configuration.**

A configuration is identified by its covariate values, and its artefact is
named from them. That is unhelpful exactly where it matters: three tuned
system prompts share a long prefix, so the readable half of each name is
identical by construction and only a hash separates them. A reader
comparing them learns nothing from the name — what distinguishes the
variants is the idea under test, which only the author can state.

An exploration entry may now carry **`configurationName:`** — a handle, in
your words, for what the variant *is*:

```yaml
explorations:
  - temperature: 0.7
    configurationName: hot-and-loose
```

It travels into the explore artefact as `configurationName` (published in
`mavai-explore-1` by mavai-R 0.10.9) and reappears wherever a reader meets
the configuration: the run's own progress and summary lines while it
samples, and the reports afterwards.

**A handle is not a covariate.** It takes no part in resolution, never
enters the configuration's identity, never names a file, and cannot make a
grid point: an entry declaring nothing but a handle is refused, and two
entries differing only by their handles are still one population and
refused as duplicates. It is prose — bounded at 256 characters, with the
empty string refused rather than taken for absence — so it carries no
uniqueness guarantee, and two configurations may share a handle and remain
two configurations.

**The base is reported as `base`.** The run announced each configuration by
the identity its factor values spell, then the report of that same run
called the base "base" — two names for one configuration, minutes apart.
One rule now serves the progress line, the abort note, and the run
summary: the base by its role, then the author's handle, then the stated
identity. The artefact filename is untouched and still spells the factor
values, which is the one place identity belongs.

Nothing to do on upgrade: `configurationName:` is optional, and a services
file without one behaves exactly as before.

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
