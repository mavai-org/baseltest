# baseltest User Guide

The complete reference for baseltest's declarative surface: the run postures (test, measure, explore, optimize, check, report), the contract file format, the `mavai-services.yaml` service-definition file, the `mavai-bindings.py` registrations file, and how to bind a service so baseltest can invoke it.

New to baseltest? Start with the [getting-started guide](GETTING-STARTED.md) — it walks one example from zero to a verdict. This guide is the reference you come back to: every file, every key, every option.

## Table of contents

- [Introduction](#introduction)
- [Part 1: The contract file (`mavai-contract/1`)](#part-1-the-contract-file-mavai-contract1)
- [Part 2: The run postures — experiment and test types](#part-2-the-run-postures--experiment-and-test-types)
- [Part 3: The services file (`mavai-services.yaml`)](#part-3-the-services-file-mavai-servicesyaml)
- [Part 4: The bindings file (`mavai-bindings.py`)](#part-4-the-bindings-file-mavai-bindingspy)
- [Part 5: Binding your service — a walkthrough](#part-5-binding-your-service--a-walkthrough)

## Introduction

baseltest tests services that do not behave the same way twice — LLM-backed services above all, but also ML models, randomised algorithms, and anything network-dependent. A stochastic service does not pass or fail a single invocation; it succeeds at a *rate*. baseltest treats that rate as the thing under test: it runs the service repeatedly, judges each response against declared criteria, and renders a verdict backed by real statistics (Wilson confidence bounds, feasibility-checked sample sizes) rather than a green tick over one lucky sample. It is the Python member of the [mavai](https://mavai.org) family, sharing its statistical methodology with [punit](https://github.com/mavai-org/punit) (Java) and [feotest](https://github.com/mavai-org/feotest) (Rust); every formula is validated against the family's [statistical oracle](https://github.com/mavai-org/mavai-R).

The declarative surface is built from three files:

| File | Name | Role |
|---|---|---|
| Contract file | **yours** (e.g. `basket-builder.yaml`) | *What you are examining*: the inputs, what a good response looks like, and optionally the bar it must clear. Passed explicitly to every verb; identified by its `format:` key, never its filename. Keep as many as you have things to test. |
| `mavai-services.yaml` | **fixed** | *What the service is*: named, configured service definitions, plus any exploration grid and optimization entries. Discovered automatically beside the contract file, then in the working directory. |
| `mavai-bindings.py` | **fixed** | *Code registrations*: bindings that invoke your service, plus custom transforms, checks, scorers, and steppers. Discovered and imported automatically, exactly like the services file — the same trust model as pytest's `conftest.py`. |

The contract file is deliberately **posture-free**: whether a run judges, records, sweeps, or searches is decided by the verb you invoke it with, never by a key in the file. The contract carries the *claim*; the invocation carries the *budget*.

Everything a run generates lands under one directory, `_baseltest/`, in the working directory — one `.gitignore` line, one `rm -rf` for a clean slate:

```
_baseltest/
├── baselines/       # measure: one baseline artefact per run
├── verdicts/        # test: one verdict record (family XML schema) per run
├── explorations/    # explore: <contract-id>/ with one artefact per configuration
├── optimizations/   # optimize: <contract-id>/ with one artefact per run id
└── reports/         # report: rendered HTML
```

When the contract file runs out of expressive power, you graduate: take direct authorship of the service contract in Python (`baseltest.contract`) — the same object the file was compiled into, evaluated by the same engine. Nothing in this guide is lost by graduating; the file format is a front-end.

## Part 1: The contract file (`mavai-contract/1`)

A contract file is YAML (YAML 1.2, safe construction). Its complete top-level vocabulary:

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | Must be exactly `mavai-contract/1`. |
| `contract` | yes | The contract's identity — a non-empty string naming the claim (e.g. `basket-builder-returns-valid-baskets`). Names artefacts and appears in every report. |
| `service` | yes | The service under test: a `@binding` name, or a service entry defined in `mavai-services.yaml`. |
| `transforms` | no | The **views** block: named transformations of the response, shared by every check that names them via `in:`. See [Transforms and views](#transforms-and-views). |
| `inputs` | yes | The per-sample inputs the run cycles through. See [Inputs](#inputs). |
| `criteria` | yes | The acceptance criteria. See [Criteria](#criteria). |
| `intent` | no | `verification` (default) or `smoke`. See [Intent](#intent-and-confidence). |
| `confidence` | no | The contract-level statistical confidence, a number in (0, 1); default 0.95. Individual criteria may override it. |
| `latency` | no | Per-percentile latency bounds judged on test runs. See [Latency](#the-latency-block). |

Three keys are **reserved** for future format versions and refused with a pointer: `facets:`, `covariates:`, `budget:`. Two families of keys are **withdrawn** and refused with the reason: `kind:` (the run mode is the invocation verb, never a file key) and the sizing keys `samples:` / `samples-per-config:` (the invocation carries the budget: `--samples N`, `--samples-per-config N`). Any other unknown key is refused by name.

### Inputs

`inputs:` is a non-empty list. Each entry is one of three shapes:

```yaml
inputs:
  - "a dozen eggs, please"            # a scalar: one value, passed as the single argument
  - ["tok-visa-4242", 2500]           # a flat list of scalars: one value per service
                                      #   parameter, splatted positionally
  - input: "a dozen eggs, please"     # an {input, expected} entry: this input's own
    expected:                         #   expectations, judged only on samples driven
      - in: basket                    #   by this input
        path: "$.items[*].name"
        contains: "egg"
```

Input values are JSON-expressible scalars (string, number, boolean); a list must be flat and non-empty — interpreting a value (a path, an identifier) is the service's business, not the format's. The run cycles through the inputs round-robin, one input per sample.

`expected:` takes a single form mapping or a non-empty list of them, using exactly the postcondition-form vocabulary below (except `parses:`, which is criterion-level). Per-input expectations require the contract to declare **exactly one** criteria entry — with several, their owner would be ambiguous. A failing per-input expectation reports its reason prefixed with the input it judged.

### Criteria

`criteria:` is a non-empty list. Each entry accepts:

| Key | Meaning |
|---|---|
| `name` | The criterion's label in output, artefacts, and failure distributions. Optional — defaults to `criterion-<n>-<first form>`; names must be unique within the contract. |
| `threshold` | The declared bar: a number in (0, 1). A criterion **with** a threshold is judged against it (a *declared* criterion). A criterion **without** one is *empirical*: its bar comes from a measured baseline (see [test](#basel-test)). `threshold: empirical` is reserved. |
| `threshold-origin` | Optional provenance: the category of source the bar comes from — e.g. `sla`, `slo`, `regulatory`. Pure metadata, recorded in artefacts and reports. |
| `contract-ref` | Optional provenance: the human-readable reference (e.g. `"Payment Provider SLA v2.0 §4.1"`). |
| `tolerate` | An **empirical** criterion's sizing claim: the lowest true pass rate you are willing to accept before the test should fail, a number in (0, 1). Feeds risk-driven run sizing at test time. Contradictory alongside `threshold:` (a stipulated bar carries no baseline claim) — declaring both is refused. |
| `confidence` | Per-criterion override of the contract-level confidence, a number in (0, 1). |
| `postconditions` | A non-empty list of postcondition forms (below). |
| *(form shorthand)* | For a single-check criterion, any one form key may sit directly on the entry: `contains: "hello"` is shorthand for a one-entry `postconditions:` list. |

A sample **passes a criterion** only when every one of its postconditions holds; a criterion's observed rate is the fraction of samples that passed it. A trial's failure reason is the *first* failing check's reason — order your checks so the most diagnostic one fails first.

#### Postcondition forms

Each postcondition entry declares exactly one form, optionally qualified by `in:` (the subject view) and `path:` (a structural selector):

| Form | Argument | Holds when |
|---|---|---|
| `equals` | string | The subject equals the string exactly. |
| `one-of` | list of strings | The subject is any one of the listed strings. |
| `contains` | string | The subject contains the substring. |
| `matches` | string (regex) | The regular expression matches somewhere in the subject (`re.search` semantics). |
| `parses` | view name | Computing the named view *is* the check: the transformation succeeding is a pass, a `TransformError` is a failed trial. Takes no `in:` — it names its view directly. |
| `satisfies` | check name | The named `@check` predicate (registered in `mavai-bindings.py`) holds for the subject value. |

`in:` names the view whose value the check judges; without it, the check judges the raw response text (`raw` is the reserved name for it, should you want to be explicit). `path:` qualifies the string forms only (`equals`, `one-of`, `contains`, `matches`) and requires `in:` naming a declared view — the raw response is unstructured text.

#### `path:` — structural selection

A `path:` check selects into a view's structured value and applies its string form to every selected value's string projection. The format pins its standards: **RFC 9535 JSONPath** for values in the JSON data model, **XPath 1.0** for XML documents. Every path expression is compiled eagerly at load time — a bad expression is a refusal before any invocation, and `basel check` validates it with zero samples.

Which language applies:

- A view from the stock `json` or `yaml` transform takes JSONPath; a view from the stock `xml` transform takes XPath.
- A view from a **custom** `@transform` takes either — the expression's own syntax decides: an expression starting with `$` compiles as JSONPath (RFC 9535 mandates the `$` root), anything else validates as XPath 1.0. Because a custom transform's return type has no load-time guarantee, the value's type is checked on every trial: a dict or list for JSONPath, a parsed `xml.etree.ElementTree.Element` for XPath. A mismatch — plain text, or XML left as an unparsed string — fails that trial with the type named. A custom transform wanting XPath must return the parsed element, not XML text.

Selection semantics, uniform across languages:

- An **empty selection fails the trial** with its own reason — which means a filter selector (`$.items[?@.name == 'egg'].quantity`) asserts the item's presence for free.
- A non-empty selection requires **every** selected value to satisfy the form: one bad quantity among five items fails that trial.
- Scalars compare by content (strings) or by their JSON text (numbers, booleans, null) — so `equals: "true"` matches a JSON `true`, and `equals: "12"` matches the number 12.
- Selecting a JSON object or array under a string form is a per-trial type failure — structure is selected *through*, not compared as text.

#### The view taxonomy in one rule

A view holding **text** takes the string forms. A view holding **structure** takes `path:` (whose selected scalars are judged by the string form it qualifies) and `satisfies:`. A string form applied directly to a structured value is a per-trial type failure, never a silent stringification. `parses: <view>` makes computing the view itself the check.

### Transforms and views

```yaml
transforms:
  basket: json          # a stock transform: parse each response as JSON
  judged: my-judge      # a registered @transform from mavai-bindings.py
```

The `transforms:` block declares named **views**: each is a transformation of the raw response, computed **at most once per response** and shared by every check that names it — a semantic guarantee, not an optimisation. `raw` is reserved and cannot be declared. The transformation name is either a stock one or a registration:

| Transform | Produces | Notes |
|---|---|---|
| `json` | The parsed JSON value | A non-parsing response is a failed trial (`transform failed…`), never an abort. |
| `xml` | A parsed `ElementTree.Element` | Same failure semantics. XPath 1.0 applies. |
| `yaml` | The YAML document, projected into the JSON data model | YAML 1.2 core schema, safe construction only; a multi-document stream, non-core tag, non-string mapping key, or expansion past the budget is a failed trial. JSONPath applies. |
| *registered name* | Whatever the `@transform` callable returns | See [Part 4](#transform--named-transformations). Structured returns are addressable with `path:`. |

### The `latency:` block

Reliability has a second axis: not just *whether* the service answers correctly, but *how long the correct answers take*. A contract may assert per-percentile upper bounds, judged on **test** runs over the durations of **passing samples only** — the timing of wrong answers does not characterise the correct path. Latency gates the verdict by conjunction with the functional criteria: a test passes only when both dimensions do.

Two mutually exclusive shapes:

```yaml
latency:                # explicit: SLA-style ceilings, in whole milliseconds
  p95: 500
  p99: 1500

latency:                # empirical: bounds derived from the measured baseline's
  empirical: [p95, p99] # latency profile at test time, at the test's own size
```

| Key | Meaning |
|---|---|
| `p50` / `p90` / `p95` / `p99` | Explicit ceiling for that percentile, a positive whole number of milliseconds. Ceilings must be non-decreasing across percentiles — a tighter bound on a higher percentile contradicts itself. |
| `empirical` | A non-empty list of percentiles (from the same four, each at most once) whose bounds are derived from the measured baseline. Contradictory alongside explicit ceilings. |
| `confidence` | The derivation confidence for empirical bounds; recorded for explicit ones. A number in (0, 1). |
| `threshold-origin` / `contract-ref` | The same provenance metadata as on criteria. |

Each percentile is judged only when the passing-sample count can support it (the family's minimum-contributing-samples gate). A bound the run's passing samples could not estimate renders the composite verdict **INCONCLUSIVE** — no judgement was possible, so no assertion can rest on it — and `basel test` exits 3, distinct from a failure.

### Intent and confidence

`intent: verification` (the default) is the full statistical posture. `intent: smoke` is the cheap first try: a small default run (n = 5) with no statistical verdict — fine for wiring things up, not for standing guard. `confidence:` sets the contract-level confidence for threshold derivation and judgement (default 0.95); a criterion's own `confidence:` overrides it locally, and `--confidence` on the invocation overrides the file.

## Part 2: The run postures — experiment and test types

One contract file, six verbs. The first four invoke the service; `check` and `report` never do.

| Verb | Posture | Sizing | Artefact |
|---|---|---|---|
| `basel test` | **Judge**: a statistical verdict on thresholded criteria and latency bounds | Derived minimum, `--samples N`, or risk-driven | Verdict record (XML) in `_baseltest/verdicts/` |
| `basel measure` | **Record**: every criterion characterised, no verdict | `--samples N` required | Baseline artefact in `_baseltest/baselines/` |
| `basel explore` | **Sweep**: every configuration in the service's grid, descriptively | `--samples-per-config N` (default 5) | One artefact per configuration |
| `basel optimize` | **Search**: iterative configuration search driven by a stepper | `--samples-per-iteration N` (default 20) | One full-history artefact per run id |
| `basel check` | **Compile**: every load-time join validated, zero samples | — | — |
| `basel report` | **Render**: HTML from persisted artefacts, post-hoc | — | `_baseltest/reports/` |

Exit codes are contractual, made for CI: **0** success · **1** judgement failure (a declared bar or latency bound was breached) · **2** refusal (the service was never invoked: malformed file, unsupportable configuration, provider rejection, nothing to render) · **3** unsupportable (the evidence cannot carry the assertion in either direction).

### `basel test`

```bash
basel test contract.yaml [--samples N] [--tolerate RATE|CRITERION=RATE]...
           [--confidence C] [--power P] [--accept-weak-design] [--json] [--force]
           [--baseline-dir DIR] [--verdict-dir DIR] [--no-verdict-xml] [--html-report PATH]
```

A test judges the contract's **declared** criteria against their thresholds and its **empirical** criteria against measured baselines, plus any `latency:` bounds. The verdict for each is a claim about the *true* rate at the stated confidence, computed from a Wilson lower bound — a high observed rate over too few samples honestly fails. Every run opens with the **run-plan line**: its n and where that value came from; no sample ever runs on a number you can't see.

**Sizing declared criteria.** With no flag, the run sizes itself at the *derived minimum* — the smallest n that can support every declared bar at its confidence. That minimum is the weakest admissible design (only a perfect run clears the bar). A derived minimum above **100 samples** is refused before a single invocation, naming the number to type; `--samples N` runs any size deliberately (still feasibility-checked — a size that cannot support a declared bar is refused).

**Sizing empirical criteria — risk-driven.** An empirical criterion's bar is derived from its baseline; its run size is computed from your stated risk: the worst acceptable true rate (`tolerate:` in the file, or `--tolerate` on the invocation — a rate like `0.84` or a percentage like `84`; the bare form addresses a contract with exactly one empirical criterion, `CRITERION=RATE` repeats for several), the confidence (`--confidence`), and, advanced, the statistical power with which a genuine drop to the tolerated rate must be caught (`--power`, default 0.8). On an interactive terminal, unclaimed values are prompted for in plain language; non-interactively they are refused. A weak design is confirmed interactively or accepted with `--accept-weak-design` (for automation); `--json` emits machine-readable sizing output and implies non-interactive. `--samples` and `--tolerate`/`--power` are contradictory sizing instructions and refused together. `--force` (with `--samples`) designs the test anyway when the tolerance is at or above the proven baseline, where the required-size search is undefined.

**Before a baseline exists**, an empirical criterion is skipped with a one-line indicator pointing at `basel measure`; a test whose criteria are *all* unthresholded and baseline-less is refused — nothing to test. A baseline is resolved only when its recorded identity matches the service's currently-resolved identity; any drifted configuration key or covariate refuses the run, naming the key (see [drift](#covariates-and-drift)).

**Outputs.** The composite verdict and per-criterion lines print to the console; a verdict record in the family's XML schema is persisted to `--verdict-dir` (default `_baseltest/verdicts/`) unless `--no-verdict-xml`; `--html-report PATH` additionally renders the self-contained HTML summary inline (the same renderer as `basel report test`, so the two outputs are identical — the flag never changes the exit code).

### `basel measure`

```bash
basel measure contract.yaml --samples N [--assert] [--baseline-dir DIR]
```

A measurement records *every* criterion — rate, variance, failure distribution — with no verdict: a declared bar is noted against the evidence as *met* or *not met*, a recorded fact. The run always persists a **baseline artefact** into `--baseline-dir` (default `_baseltest/baselines/`): the durable record of what was observed, under exactly which resolved service identity (configuration values, covariates, provenance). When at least one sample passed, the baseline also records the run's **latency profile** — the gated percentiles and the full ascending vector of passing-sample durations, the raw material from which a later test derives latency bounds at its own size and confidence.

`--samples` is required: a measurement's budget is an experimental-design decision, so it must be typed. 1,000 is a solid baseline-grade count; a smaller deliberate budget is legitimate — an empirical bar derived from a smaller baseline simply widens honestly.

`--assert` opts into failing *after* recording (the baseline is persisted regardless): exit 1 if a declared bar was not met, exit 3 if the sample size cannot support the judgement. `--html-report` is refused on measure — its product is the baseline artefact, not a report.

### `basel explore`

```bash
basel explore contract.yaml [--samples-per-config N] [--explorations-dir DIR]
```

An exploration runs the contract over **every configuration in the service's grid** — the baseline `configuration:` plus each `explorations:` entry (see [Part 3](#explorations--the-configuration-grid)) — with explore's descriptive posture: no thresholds consulted, no verdict rendered, one artefact per configuration written under `--explorations-dir` (default `_baseltest/explorations/<contract-id>/`), named by the grid's discriminating factor values. Triage, not judgement: the default 5 samples per configuration is the point, and no count is ever refused as too small.

Where a grid spans providers with differing support for a configuration key (`response-schema`, `prompt-caching`, `thinking`), the affected grid point runs without the key, announced by a console note — degradation is honest, never silent. Exploration *comparison* reports are rendered by the family's [mavai](https://github.com/mavai-org/mavai/releases) tool: `mavai explore <dir> [-o report.html]`.

### `basel optimize`

```bash
basel optimize contract.yaml [id] [--all] [--samples-per-iteration N] [--optimizations-dir DIR]
```

Runs one of the service's declared `optimizations:` entries (see [Part 3](#optimizations--iterative-search)): an iterative configuration search in which a **stepper** proposes each next configuration and a **scorer** judges each iteration. Each iteration runs like a miniature measure — descriptive, no verdict — and the full history (every configuration, score, per-criterion failure breakdown with exemplars, latency summary, and the stepper's own provenance) is persisted as one artefact per run id under `--optimizations-dir` (default `_baseltest/optimizations/<contract-id>/`).

A lone entry runs without naming it; with several declared, the `id` is required (or `--all` runs each as an independent experiment — naming an id *and* passing `--all` is refused). The run ends at `max-iterations`, on the `no-improvement-window` plateau, or when the stepper stops. Note the artefact's `convergence:` block names the best *single iteration* by score, while a noise-aware stepper's own selection (recorded in its `stepper:` block) rests on evidence pooled across visits — when they differ, trust the pooled selection.

### `basel check`

```bash
basel check contract.yaml
```

The authoring loop's compile step: validates every load-time join — the contract file's structure, every compiled `path:` expression, the services file, each exploration grid point and optimization entry, the bindings (every configuration key against the factory's signature, every input against the binding's arity) — **without running a single sample**. Exit 0 with one `ok:` line per validated fact; exit 2 with the same refusal a run would give. It belongs in your editor loop and CI.

**Paths are validated against declared shapes.** When a view's value has a declared schema — the parsed response (stock `json` view) against the service's `response-schema`, a derived view against its transformation's declared `output_schema` — every `path:` expression over it is statically resolved against that schema at load time, before a single sample is paid for. A mistyped path (`$.statments[*]` for `$.statements[*]`) is refused with **every** failing expression itemised in one message: the criterion and postcondition it sits in, the full expression, where the walk stopped, the keys actually declared there, and a nearest-match suggestion (*did you mean `statements`?*). Resolving expressions are counted in the `ok:` facts (`ok: 14 path expressions resolve against the response-schema of service 'extractor'`). The walk covers the decidable subset — member access, array indices, wildcards, union branches; filter expressions, slices, recursive descent, and open shapes **pass unverified, visibly** (`ok (unverified): …`) — no false refusals, ever. A service without a declared schema simply has no such join.

One boundary to know: zero samples means zero responses, so *response-shape* behaviour (provider reply parsing, transform outcomes) is exercised only by live samples — the framework keeps the provider adapters' extraction paths under recorded-response tests precisely because `basel check` cannot reach them. (Declared schemas move a large class of response-shape assumptions left of that boundary — that is exactly what the path validation above buys.)

### `basel report`

```bash
basel report test [--verdict-dir DIR] [--out PATH]
```

Renders a self-contained HTML report from persisted verdict records — post-hoc, never invokes a service. `--out` relocates the output (default `_baseltest/reports/test.html`). `report measure` is reserved; `report explore` points at the family's `mavai` tool, which owns exploration comparison rendering.

## Part 3: The services file (`mavai-services.yaml`)

The services file defines named services that contract files reference by `service:`. It is discovered automatically — first beside the contract file, then in the working directory — and its name is fixed and non-negotiable.

```yaml
format: mavai-services/1      # required, exactly this
services:                     # required, a non-empty mapping of service entries
  <service-name>:
    type: <type-name>         # required: 'language-model', or a @binding_factory type
    configuration: { ... }    # required: the complete baseline factor record
    explorations: [ ... ]     # optional: the configuration grid, as deltas
    optimizations: [ ... ]    # optional: declared Optimize experiments
```

Each entry accepts exactly those four keys. A configuration value placed directly on the entry is refused with the uniformity rule: **every covariate value lives inside `configuration:`** — that block is the baseline factor record, the complete set of parameter values the service runs under, communicated uniformly and recorded in every artefact's provenance. The resolved configuration is the service's *identity*: it is what a baseline is measured under, what a later test is compared against, and what names an exploration's artefacts.

`type:` selects a registered **service type**: the built-in `language-model`, or a user type registered with `@binding_factory` (whose factory signature is then the `configuration:` schema — see [Part 4](#binding_factory--configurable-service-types)). A bare `@binding` service needs **no services-file entry at all**: the contract's `service:` addresses it directly, and an entry naming its type is refused with a pointer to the factory form.

### The `language-model` type

The built-in type for a model given a job. Its `configuration:` keys:

| Key | Required | Meaning |
|---|---|---|
| `system-prompt` | **yes** | The job. Without a system prompt there is a model, but no service to test. |
| `provider` | no | A named vendor adapter: `openai`, `anthropic`, `mistral`, `ollama`, or `apertus`. Omitted, the generic OpenAI-compatible adapter applies and `MAVAI_LLM_ENDPOINT` must name your endpoint (vLLM, a gateway, a self-hosted deployment). |
| `model` | no | The model identifier, passed through verbatim. Falls back to the `MAVAI_LLM_MODEL` environment variable; a run with neither is refused. |
| `temperature` | no | The sampling temperature, passed through wherever the provider's wire format has a slot for it. |
| `top-p` | no | The nucleus-sampling parameter, a number in (0, 1]; passed through like `temperature`. |
| `thinking` | no | `adaptive` or `none` (default `none`). `adaptive` lets the model choose its own deliberation depth per response — it changes the response distribution, so it is a first-class identity factor: a baseline measured under one setting refuses a test under the other. |
| `prompt-caching` | no | `true` or `false` (default `false`). Asks the provider to cache the compiled system prompt. Correctness-invariant by construction (a cache hit reuses computation over an identical prefix); the effect is confined to latency and cost. No warmup machinery applies: the first, cache-writing invocation simply lands as the slowest recorded point, and a cache-TTL expiry mid-run mixes cached and uncached samples in one latency population — absorbed descriptively, so a bimodal p99 under caching is the cache's signature, not service degradation. |
| `response-schema` | no | A JSON Schema mapping the model is instructed to satisfy, passed through the provider's structured-output mechanism. Structured-output rules are strict: objects need `required:` and `additionalProperties: false`. Written in YAML style or pasted as JSON verbatim — both parse identically. |

Every key is a **factor**: fixed per configuration, part of the drift-checked identity, swept only across grid points — never varied within a run.

**Provider support.** Not every provider supports every key. `response-schema` is honoured by `openai`, `anthropic`, `mistral`, `ollama`, and the generic adapter, and refused by `apertus` (its hosted endpoint does not assert support). `prompt-caching` and `thinking` are currently realised by `anthropic` only; the declared-off values (`prompt-caching: false`, `thinking: none`) are honoured trivially by every provider. The rule when a provider cannot honour an *active* key is uniform: under **measure** and **test**, baseltest refuses up front rather than quietly dropping it — dropping it would change what is being measured; under **explore**, the affected grid point runs without the key, announced by a console note, so mixed-provider grids still run. One provider-specific constraint: on `anthropic`, `thinking: adaptive` cannot be combined with an explicit `temperature:` or `top-p:` — the API constrains sampling parameters while thinking, and baseltest refuses the combination at load time.

**Credentials and endpoints** live in the environment only — never in either file:

| Variable | Meaning |
|---|---|
| `MAVAI_LLM_API_KEY` | The family-wide credential, consulted first for every provider. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `MISTRAL_API_KEY` / `PUBLICAI_API_KEY` | Each vendor's conventional variable, the fallback for its provider. `ollama` needs no credential. |
| `MAVAI_LLM_ENDPOINT` | Overrides any provider's default endpoint; required when `provider:` is omitted. |
| `MAVAI_LLM_MODEL` | The default model when the configuration declares none. |

The adapters are deliberately plain: **one request per sample, no retries, no client-side response caching, no streaming, no tool use** — a silently retried failure is a resampled trial and biases the very rate under test. Failed *delivery* (an unreachable service, a server-side error) is a failed sample with the cause recorded as its failure reason; a client-side rejection (bad credential, unknown model, rejected schema) aborts the run with the provider's own explanation, because samples of a misconfigured request would measure nothing. The `anthropic` protocol requires a generation cap on every request; the adapter pins it at 4096 tokens and records that fact in provenance.

### `explorations:` — the configuration grid

```yaml
    configuration:
      system-prompt: "..."
      provider: openai
      model: gpt-4o-mini
      temperature: 0.2
    explorations:
      - temperature: 0.7                      # entry = baseline with these keys replaced
      - model: claude-haiku-4-5               # sweep another axis
        provider: anthropic
      - thinking: adaptive                    # client configuration is an axis too
        provider: anthropic
```

`explorations:` extends the baseline into a **grid**. Each entry is a non-empty mapping declaring only the values it *replaces* — its resolution is the baseline with those keys overlaid (a key with no value is refused: omit a key to keep its baseline value). The grid is the baseline plus the entries; `basel explore` consumes the whole grid, while `test` and `measure` consume exactly the baseline and behave identically with or without the section.

Two entries resolving to the same covariate point — or an entry restating the baseline — are refused: one population, one grid point (and one artefact filename). The keys any entry replaces become the grid's **swept keys**, in the type's canonical order; their resolved values identify each configuration in artefact filenames and variant labels, while every artefact's `factors:` block records the point's *full* resolved configuration, so a reader of any single artefact sees the whole picture.

### `optimizations:` — iterative search

```yaml
    optimizations:
      - id: prompt-tuning              # required when several entries are declared
        stepper: prompt-engineer       # required: a built-in or @stepper name
        stepper-config:                # the stepper factory's parameters (kebab-case)
          max-exemplars: 3
        scorer: pass-rate              # optional (this is the default)
        objective: maximize            # optional: maximize (default) | minimize
        max-iterations: 8              # required: the hard cap
        no-improvement-window: 3       # optional: stop after this many consecutive
                                       #   iterations without improvement
        initial:                       # optional: iteration 0's overlay on the baseline
          system-prompt: "You build shopping baskets."
```

Each entry declares one Optimize experiment. `id:` names the run and its artefact file (letters, digits, dots, underscores, hyphens); a lone entry defaults to the service name. `initial:` has exactly an exploration entry's merge semantics and must change something — iteration 0 is the baseline by default. A `no-improvement-window` that cannot fire within `max-iterations` is flagged as inert (advisory, not a refusal). Everything checkable without a sample — the stepper name, its config against the factory signature, targeted configuration keys, the scorer name — is validated at load time, and by `basel check`.

**Built-in steppers** (their `stepper-config:` schema is the factory's parameters):

| Stepper | Config keys | What it does |
|---|---|---|
| `prompt-engineer` | `provider`, `model`, `temperature` (default 0.5), `system-prompt` (the meta prompt), `target-key` (default `system-prompt`), `max-exemplars` (default 2) | A meta-LLM as prompt engineer: each iteration sends the current prompt, its score, and the per-criterion failure breakdown with exemplars to a meta model and treats the response as the next value of `target-key`. The meta `provider`/`model` default to the optimized service's own, so the credentials you already exported cover it and no vendor is silently pinned; the resolved meta identity is recorded in the artefact. |
| `linear-sweep` | `key`, `step`, `stop` (all required; `step` non-zero) | Walks one numeric configuration key from its starting value in fixed increments to `stop`. A fixed grid you want fully characterised is an *exploration*; what earns the sweep a place here is plateau stopping abandoning the walk early. |
| `refining-grid` | `key`, `lo`, `hi`, `step`, `min-step` (required); `confidence` (0.95), `min-improvement` (0.02), `confirmation-epochs` (2), `prefer` (`low`\|`high`) | Noise-aware, coarse-to-fine search over one numeric key: measures every value on a coarse grid over `[lo, hi]`, pools evidence per value across visits, narrows to the leader's neighbourhood at half the step down to `min-step` — a candidate is eliminated only when its uncertainty interval can no longer carry a meaningful advantage, never by a single bad round — then re-measures the finalists in independent confirmation epochs before selecting (practical ties prefer the lower value unless `prefer: high`). Its selection, finalist standings, and stopping reason land in the artefact's `stepper:` block. |

The built-in scorer, `pass-rate`, is the iteration's observed overall pass rate (it travels in artefacts under its canonical interchange name, `observed-pass-rate`). User steppers and scorers register in `mavai-bindings.py` — see [Part 4](#stepper-and-scorer--optimize-authors).

## Part 4: The bindings file (`mavai-bindings.py`)

`mavai-bindings.py` is an ordinary Python file, discovered beside the contract file (then in the working directory) and imported before the contract is instantiated — the same trust model as pytest's `conftest.py`: it is your own project file, executed because you placed it there. It exists so command-line runs can reach your code; API callers may equally register from any module they import before running. Everything in it is a **registration** made with five decorators from `baseltest.declarative`:

```python
from baseltest.declarative import binding, binding_factory, check, transform, scorer, stepper
```

### `@binding` — the service itself

```python
from baseltest.declarative import binding
from my_app import gateway

@binding("payment-gateway")
def charge(card_token: str) -> str:
    return gateway.charge(card_token).status_line()
```

Registers the code that invokes a service, under the name contract files reference via `service:`. The callable receives the contract's per-sample input values — a scalar input arrives as the single argument; a list input is splatted positionally, one value per parameter (`basel check` validates every input against the signature) — and returns **one response string**. It must be safe to invoke once per sample.

The failure semantics are load-bearing:

- An **anticipated bad response** is *returned*, for the criteria to judge. A declined charge is a response; judging it is the contract's job.
- A **failed delivery** — the service unreachable, a server-side error — is raised as `baseltest.contract.ServiceDeliveryError`: a *failed sample*, counted against every criterion with the message as its reason, and the run completes to a verdict. An unreachable service is a failed service; hiding that behind an abort would leave the rate unjudged.
- Any **other exception is a defect** — a bug, misconfiguration — and aborts the run. That is the correct response to a bug, not to a sample that happened to fail.

A bare binding takes no configuration; a services-file entry naming its type is refused with a pointer to the factory form below.

### `@binding_factory` — configurable service types

```python
from collections.abc import Callable
from baseltest.declarative import binding_factory

@binding_factory("fortune-teller")
def fortune_teller(mood: str, sincerity: int = 5) -> Callable[[str], str]:
    def tell(name: str) -> str:
        return f"{mood} fortune for {name} at sincerity {sincerity}"
    return tell
```

Registers a **configurable service type** — the seam the built-in `language-model` type itself sits on. The factory receives one grid point's resolved configuration as keyword arguments and returns the per-sample callable. **The factory's signature is the configuration schema**:

- Services-file kebab-case keys map to the factory's snake_case parameters (`system-prompt` → `system_prompt`).
- Parameters **without defaults are required** configuration keys; parameters with defaults are optional.
- Scalar type annotations (`str`, `int`, `float`, `bool`) are checked where present; configuration values must be scalars.
- A `**kwargs` factory accepts any key; otherwise unknown keys are refused at load time **with the factory's signature in the message** — as are missing required keys and mistyped values.
- Parameters must be keyword-bindable (no positional-only, no `*args`).

A type registered this way is instantiated by a services-file entry (`type: fortune-teller` plus its `configuration:`) and is not directly addressable from a contract's `service:`. Factories run at contract-load time — validation constructs the per-sample callable before any sample, and `basel check` exercises exactly this join — so they must be cheap and side-effect-light. Every resolved configuration value lands in the baseline artefact's provenance, and the grid (`explorations:`) and search (`optimizations:`) machinery work over user types exactly as over `language-model`.

### Covariates and drift

```python
@binding(
    "payment-gateway",
    covariates={
        "gateway-api": gateway.api_version(),
        "routing-rules": routing_rules_fingerprint(),
    },
)
def charge(card_token: str) -> str: ...
```

Both registration forms take `covariates=` — **computed identity**: values a YAML file cannot state, resolved from the environment at declaration time (a content fingerprint, a library version, the model behind an internal endpoint). A measure run records them in the baseline artefact's provenance; because the bindings file is imported on every invocation, a later test resolves them *afresh* — and a mismatch is refused with the drifted key named, never judged silently against evidence measured under a different identity. Compute the values at declaration time so every run re-resolves them; that is what makes drift observable.

Covariate values must be strings — format them explicitly; identity is compared verbatim. Keys the framework writes into provenance itself are reserved and refused at registration: `binding`, `runMode`, `serviceType`, `taskFile`, `taskFormat`. A key declared both as a covariate and as a factory parameter is a configuration error — one identity key, one feed. Configuration keys need none of this machinery: they join the drift-checked identity natively.

### `@transform` — named transformations

```python
import json
from baseltest.contract import TransformError
from baseltest.declarative import transform

@transform("basket-judge")
def basket_judge(raw: str) -> dict[str, object]:
    try:
        items = json.loads(raw)["items"]
    except (ValueError, TypeError, KeyError) as error:
        raise TransformError(f"response is not a basket: {error}") from error
    names = [item.get("name") for item in items if isinstance(item, dict)]
    return {"namesUnique": len(names) == len(set(names))}
```

Registers a transformation for the contract's `transforms:` block. The callable receives the raw response string and returns the value under judgement — text (for the string forms) or structure (a dict/list for JSONPath `path:` checks, a parsed `ElementTree.Element` for XPath ones). Raise `baseltest.contract.TransformError` when the response cannot be transformed: that is a **failed trial** with a transform-failure reason, never an abort; any other exception is a defect and propagates. The stock names `json`, `xml`, `yaml` are reserved.

A transformation computing derived values can declare its output's shape — `output_schema=` takes the JSON Schema as a mapping or a path to a schema file (`.json`, `.yaml`/`.yml`; a malformed schema is refused at registration):

```python
@transform("verdict-view", output_schema=VERDICT_VIEW_SCHEMA)
def derive_verdict(response: str) -> dict[str, object]: ...
```

Declaring it buys two things. **Statically**, contract `path:` expressions over the transformation's views are validated against the schema at load time and by `basel check` — the same walk, refusals, and `ok (unverified)` discipline as for the `response-schema` ([see the check verb](#basel-check)). **Per trial**, the transformation's actual output is validated against the schema — always on: a declared schema is a claim, and claims are checked — and a violation is a named trial failure (`view 'verdict-view' violates its declared output schema: …`), so view-shape drift surfaces honestly instead of silently selecting nothing.

One thing the schema is deliberately **not**: a covariate. An output schema executes after the response exists and has no influence on the service's stochastic behaviour, so it never joins the drift-checked identity — its canonical fingerprint is recorded *descriptively* in the baseline artefact's `views:` block (visible and diffable, never compared), and changing it never refuses a baseline. Contrast the `response-schema`, which constrains what the model emits — it always influences the service and is always a covariate.

### `@check` — named predicates

```python
from baseltest.declarative import check

@check("has-value")
def has_value(parsed: dict[str, str]) -> bool:
    return "value" in parsed
```

Registers a predicate for the `satisfies:` form. It receives the subject view's value (the transformed value when the check names a view via `in:`, the raw response text otherwise) and returns whether the check holds. Prefer declarative checks where they can express the claim — a named check's semantics live in code, outside the contract file, which splits the claim across two artefacts; `satisfies:` is for judgements the declarative forms genuinely cannot state.

### `@stepper` and `@scorer` — optimize authors

```python
from baseltest.declarative import IterationSummary, OptimizeContext, scorer, stepper

@scorer("p95-latency")
def p95_latency(summary: IterationSummary) -> float:
    return float(summary.latency.p95_ms) if summary.latency and summary.latency.p95_ms else 1e9

@stepper("halving", configuration_keys=("key",))
def halving(key: str, floor: float):
    def step(current: dict, ctx: OptimizeContext) -> dict | None:
        value = current[key] / 2
        return {**current, key: value} if value >= floor else None
    return step
```

`@stepper` registers a **factory**, mirroring the binding-factory form: its snake_case parameters are the entry's `stepper-config:` schema (kebab-case keys map by name, defaults are optional keys, scalar annotations are checked), and it returns the step function — `step(current, ctx)` receiving the whole current configuration mapping and the run's context, returning the whole next configuration or `None` to stop. State an algorithm keeps across iterations lives in the factory's closure — the framework carries no stepper state. `configuration_keys=` names factory parameters whose *values* must be existing keys of the optimized service's configuration, validated at load time (that is how `linear-sweep`'s `key:` and `prompt-engineer`'s `target-key:` are checked). Built-in stepper names cannot be re-registered.

The context types a stepper decides from (all importable from `baseltest.declarative`): `OptimizeContext` (the full `history` oldest-first, the objective-aware `best`, the upcoming `iteration` index, and `iterations_remaining` — budget visibility), `IterationResult` (one completed iteration: `config`, `score`, `summary`), and `IterationSummary` (what a scorer consumes: `passes`, `samples`, the derived `pass_rate`, `failures_by_criterion` mapping criterion names to `FailureDetail` counts with `FailureExemplar` input/reason pairs, and the gated `LatencySummary`).

`@scorer` registers the iteration-judging function: `fn(summary) -> float`, in objective units — pair it with the entry's `objective:` direction.

## Part 5: Binding your service — a walkthrough

How to get from "I have a service" to "baseltest invokes it", for each service shape.

**A language-model service: two files, no Python.** Declare the service in `mavai-services.yaml` (`type: language-model`, the system prompt, provider, model — [Part 3](#the-language-model-type)), export the credential, write the contract. No bindings file exists; the built-in adapters do the invoking. This is the zero-code path the [getting-started guide](GETTING-STARTED.md) walks.

**Anything you can call from Python, fixed configuration.** Write `mavai-bindings.py` beside your contract with one `@binding` whose name is the contract's `service:`. Wrap your client so the binding returns one response string per invocation, and sort the failure channels: return anticipated bad responses, raise `ServiceDeliveryError` for failed delivery, let genuine defects propagate. No services file is needed.

```python
# mavai-bindings.py
from baseltest.contract import ServiceDeliveryError
from baseltest.declarative import binding
import my_client

@binding("recommender")
def recommend(user_id: str, item_count: int) -> str:
    try:
        return my_client.recommend(user_id, count=item_count).to_json()
    except my_client.Unreachable as error:
        raise ServiceDeliveryError(f"recommender unreachable: {error}") from error
```

```yaml
# recommender.yaml
format: mavai-contract/1
contract: recommender-returns-plausible-lists
service: recommender
inputs:
  - ["alice", 5]          # one value per binding parameter, in order
  - ["bob", 3]
criteria:
  - threshold: 0.9
    postconditions:
      - in: parsed
        path: "$.items[*].id"
        matches: '^[A-Z]{2}-\d+$'
transforms:
  parsed: json
```

**A configurable service — you want a grid, a search, or several instances.** Register a `@binding_factory` instead; its signature becomes the `configuration:` schema, and the service is declared in `mavai-services.yaml` with `type:` naming it. Now `explorations:` sweeps its parameters and `optimizations:` searches them, exactly as for a language model.

**Identity beyond the configuration.** Whatever shape you chose, declare `covariates=` for identity facts the files cannot state — versions, fingerprints, the world the service ran under — so baselines refuse rather than silently mismatch ([covariates and drift](#covariates-and-drift)).

**Then compile before you run.** `basel check contract.yaml` validates every join — contract against services file against bindings, every input against the binding's signature, every path expression, every grid point and optimization entry — with zero samples. When it prints its `ok:` facts, `basel test` and `basel measure` will run as declared; when it refuses, the message is the same one a run would have given, with the signature or vocabulary you need in it.

A closing rule of thumb on where logic belongs: the **binding** invokes; the **transforms** parse; the **criteria** judge. Keep judgement out of the binding (a binding that pre-filters bad responses biases the rate under test) and parsing out of the checks (a view is computed once and shared). The family invariant that judging code never sees the *input* is enforced by construction — checks address the response and its views only; per-input judgement is the contract's `expected:` machinery, never your code's.
