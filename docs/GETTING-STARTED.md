# Getting started with baseltest

baseltest tests services that don't behave the same way twice — LLM-backed services above all. You declare what a good response looks like and what pass rate you require; baseltest runs the service repeatedly and gives you a verdict backed by real statistics, not a green tick over one lucky sample.

For your first test you write **two small files and no Python**.

## Setup

```bash
# Python 3.11+ required
pip install "baseltest[declarative]"    # the baseltest package ships the `basel` command

export MAVAI_LLM_API_KEY="..."   # or your vendor's usual variable, e.g. OPENAI_API_KEY
```

baseltest ships basic adapters for `openai`, `anthropic`, `mistral`, `ollama` (local, no key), and `apertus` (the fully open Swiss model, served via the Public AI utility) — declare one as `provider:` in the service configuration below. Prefer your own OpenAI-compatible endpoint (vLLM, a gateway)? Omit `provider:` and set `MAVAI_LLM_ENDPOINT` instead. Credentials live in the environment only — they never appear in either file. The adapters are deliberately plain: one request per sample, no retries and no caching, because a silently retried failure would bias the very rate under test. Failed delivery is judged, not hidden: an unreachable service or a server-side error counts as a failed sample with the cause recorded as its failure reason — an unreachable service is a failed service — while a client-side rejection (bad credential, unknown model, rejected schema) aborts the run with the provider's own explanation, because samples of a misconfigured request would measure nothing.

## File 1: the service definition (`mavai-services.yaml`)

This file says what your service *is*. For a language-model service, that means the model given a job — the system prompt is required, because without one you have a model, but no service to test:

```yaml
format: mavai-services/1
services:
  basket-builder:
    type: language-model
    configuration:
      provider: openai
      model: gpt-4o-mini
      system-prompt: >
        You translate shopping instructions into a JSON basket.
      temperature: 0.2
      response-schema:
        type: object
        additionalProperties: false    # structured-output rules are strict:
        required: [items]              # objects need required: and
        properties:                    # additionalProperties: false
          items:
            type: array
            items:
              type: object
              additionalProperties: false
              required: [name, quantity]
              properties:
                name: { type: string }
                quantity: { type: integer }
```

The `response-schema` tells the model — through the provider's structured-output mechanism — exactly what shape to return, which is often the single strongest lever on an LLM service's pass rate. It is part of the service's identity like every other parameter. (Not every provider supports it; under `measure` and `test`, baseltest refuses up front rather than quietly dropping it, because dropping it would change what you are measuring. An `explore` run over a mixed-provider grid degrades honestly instead: the schema-less provider's configuration runs without the schema, announced by a console note — carry the output shape in the system prompt to keep such comparisons fair.)

The schema above is written in YAML style, but only the *file* is YAML — on the wire, baseltest serialises it to exactly the JSON the provider APIs expect. And since YAML is a superset of JSON, you can also paste a JSON Schema in verbatim; both forms parse to the identical structure:

```yaml
      response-schema: {
        "type": "object",
        "additionalProperties": false,
        "required": ["items"],
        "properties": {"items": {"type": "array"}}
      }
```

Everything in `configuration:` is part of the service's identity, and baseltest records the resolved values (including the model, even when it came from the environment) in every result — so you always know exactly what was measured.

## File 2: the contract (`basket-builder.yaml` — the name is yours)

This file says what you are examining: the inputs, what a good response looks like, and - optionally - the bar it must clear. It is deliberately **posture-free**: whether a run judges or measures is decided by how you invoke it, not by the file.

A note on the two filenames: `mavai-services.yaml` (like `mavai-bindings.py`) is **fixed** — the reader discovers it by name, so the name is namespaced and non-negotiable. The contract file is never discovered; you pass it to the verb explicitly, so its name is entirely yours — name it for what it tests, and keep as many as you have things to test. The file identifies itself through its `format:` key, not its filename.

```yaml
format: mavai-contract/1
contract: basket-builder-returns-valid-baskets
service: basket-builder

transforms:
  basket: json                         # parse each response as JSON; the result is 'basket'

criteria:
  - name: response-is-a-valid-basket
    threshold: 0.95
    postconditions:
      - in: basket
        path: "$.items[*].name"
        matches: '\w'                  # every item has a real name
      - in: basket
        path: "$.items[*].quantity"
        matches: '^[1-9][0-9]*$'       # every quantity is a positive integer

inputs:
  - input: "a dozen eggs, please"
    expected:                          # this input's own expectation
      - in: basket
        path: "$.items[*].name"
        contains: "egg"
  - "two bottles of milk and a loaf of bread"
  - "add three apples"
```

The file reads top to bottom as *machinery, rules, cases*. The `transforms:` block declares a **view**: a named transformation of the response, computed at most once per response and shared by every check that names it via `in:`. A check without `in:` judges the raw response text (`raw` is the reserved name for it, should you want to be explicit). Reading the whole file aloud: invoke `basket-builder` repeatedly, cycling through the three instructions; each response must parse as JSON, every item must carry a real name, every quantity must be a positive integer — and the egg order must actually contain eggs. Because a `path` check fails the trial when it selects nothing, a basket with no items fails too; and a `path` check judges **every** value it selects: one bad quantity among five items fails that trial.

## Run it

```bash
basel test basket-builder.yaml
```

```
n = 52 (derived: criterion response-is-a-valid-basket's threshold 0.95 requires at least 52 samples)
contract basket-builder-returns-valid-baskets: PASS
  criterion response-is-a-valid-basket: PASS
    52 of 52 responses met expectations
    observed rate 1.0000; we can be 95% confident the true rate is at least 0.9505 — clears your 0.95 threshold
```

That last line is the point of baseltest: the verdict is not "100% ≥ 95%". It is a claim about the *true* rate, at a stated confidence, computed from a Wilson lower bound — a high observed rate over too few samples would honestly fail. Notice what the derived minimum means: at n = 52, only a perfect run can clear a 0.95 bar. A larger `--samples` buys slack — at n = 100, two failures still pass (the lower bound of 98/100 is 0.9530). Add `--html-report report.html` for a self-contained summary page.

The first line is the **run-plan line**: every run states its n and where the value came from — no sample ever runs on a number you can't see. The contract file carries the **claim**; the invocation carries the **budget**. With no flag, a test of declared thresholds runs at the *derived minimum* — the smallest n that can support every bar at its confidence. That minimum is the weakest admissible design (only a perfect run clears the bar): fine for wiring things up, not for standing guard. A derived minimum above **100 samples** (roughly, any bar above 0.96) is refused before a single invocation, naming the number to type; `--samples N` runs any size deliberately (still feasibility-checked), and `intent: smoke` gives a cheap pass with no statistical verdict. *Empirical* criteria — bars derived from a measured baseline — are sized from your stated risk instead: see **Sizing by risk** below.

`--samples N` works on `test` and `measure` alike, and the confidence bound is honestly computed at the size actually run — a cheap 50-sample check is still a statistically meaningful one.

**`test` judges; `measure` records.** The same file, run as `basel measure basket-builder.yaml --samples 1000`, records *every* criterion (rate, variance, failure distribution) — a declared bar is noted against the evidence as *met* or *not met*, a recorded fact rather than a verdict, and the run always exits successfully — and always persists a **baseline artefact** into `_baseltest/baselines/`: the durable record of what was observed, under exactly which service configuration. When at least one sample passed, the baseline also records the run's **latency profile** — the gated percentiles (p50/p90/p95/p99, each present only when the passing-sample count can support it) and the full ascending vector of passing-sample durations, the raw material from which a later consumer derives latency bounds at its own sample size and confidence; only passing samples contribute, because the timing of incorrect behaviour does not characterise the correct path. (Everything baseltest generates lives under the single `_baseltest/` directory — one `.gitignore` line, one `rm -rf` for a clean slate.) A test run persists no baseline: its product is the verdict, written into `_baseltest/verdicts/` as the verdict record described below. `measure` is the one verb with no default n — a measurement's budget is an experimental-design decision, so it must be typed: `--samples 1000` is a solid baseline-grade count, and a smaller deliberate budget is legitimate (an empirical bar derived from a smaller baseline simply widens honestly). A criterion with no `threshold:` is an **empirical** criterion — its bar comes from evidence rather than declaration. Before any baseline exists, `test` skips it with a one-line indicator; but once you have run `basel measure`, the next `test` finds the baseline and judges the empirical criterion against it — *no worse than measured*, the bar derived from the baseline's recorded evidence at the test's own sample size, the verdict line naming the artefact it judged against:

```
criterion spirits-stay-polite: PASS
  observed rate 1.0000; we can be 95% confident the true rate is at least 0.9867
  — clears your 0.9654 threshold (empirical, fortune-teller-…-b44846234567.yaml)
```

The workflow is **measure once, test forever after** — and the baseline only matches if it measured *the same thing*: same contract, same inputs, same service configuration. Change the model or the system prompt and the test tells you the baseline no longer applies (naming the differing settings) instead of quietly judging against stale evidence.

## Sizing by risk: tell it what you tolerate

For empirical criteria, the sample size is a **derived output of your stated risk**, not a guess. The empirical bar is derived *at the test's own size* and falls as the sample shrinks, so dialling `--samples` down quietly buys an easier pass — the trap this closes. `basel test` instead asks two plain questions — the lowest real pass rate you will accept, and how sure you want to be — and computes the smallest n at which a service truly at that rate fails about four times out of five (`--power` overrides the 0.80 default).

Declare the claim wherever it belongs:

- **In the contract file** — the criterion key `tolerate: 0.84` (the worst acceptable true rate), with an optional per-criterion `confidence:` override. A CI run then needs no flags.
- **On the command line** — `--tolerate 84 --confidence 95` (rates or percentages); a flag overrides the contract key. Against several empirical criteria, name each claim: `--tolerate keeps-up=0.84 --tolerate stays-polite=0.9` (the bare form is refused). The largest requirement governs the run; the output marks which criterion set it.
- **Interactively** — with no claim declared and a terminal attached, the test asks, shows each criterion's proven baseline rate, and confirms before running. With no terminal it refuses: exit 2, zero invocations, the exact flags named.

Every mode explains the n that actually runs. One claim gets a sentence:

```
This test needs 214 samples (computed from your declared tolerance).
If this test passes, you can be 95% confident the true pass rate is at least 85%. This design will catch a genuine drop to 84% about 80% of the time.
```

Several claims get a table, one row per claim:

```
This test needs 563 samples (computed from your declared tolerances).

  criterion             tolerates  confidence  drop caught  a pass proves  needs alone
  fortune-is-delivered        84%         95%   about 100%   at least 89%          134
  spirits-stay-polite         97%         95%    about 80%   at least 98%          563  ← sets the run size
```

Reading the columns:

- **criterion** — the promise being priced; one row per empirical criterion with a declared tolerance.
- **tolerates** — the worst true success rate you said you can live with: your `tolerate:` value.
- **confidence** — how sure a verdict must be before it counts; the same confidence the pass bar is built at.
- **drop caught** — if the service really has fallen to the tolerated rate, how often a run of this size will catch it.
- **a pass proves** — what passing entitles you to claim: the true rate is at least this, at the stated confidence.
- **needs alone** — the samples this claim would need by itself. The largest number wins the run size; `←` marks the claim that set it, and every other claim gets caught more often than it asked for.

`--samples N` is the other sizing mode, and the two don't mix: `--samples` with `--tolerate` or `--power` is refused as contradictory. On its own — including against contract-file `tolerate:` keys — it never runs silently: the run states what that n buys, and a **weak design** needs a confirmation defaulting to No (`--accept-weak-design` restores automation). A tolerance **at or above** the proven baseline is over-reach — a test designed to fail, which more samples only make worse — so no size is computed: re-measure and set the tolerance against the new proven rate, confirm past the warning interactively (default No), or pass `--force` plus an explicit `--samples` in automation. A large computed n is never refused; it reports its cost and suggests a wider tolerance or lower confidence. `--json` emits the sizing block machine-readably and implies non-interactive.

The decision rule is untouched — risk-driven sizing only chooses *how many* samples feed the same empirical derivation and judgement. The HTML report's **Run design** block records the deal: the approach (`confidence-first (risk-driven)` or `sample-size-first`), the claims and computed size, and — for a run smaller than its baseline's measurement — the drop it could actually catch and the estimated time saving.

## Testing your own (non-LLM) service

Anything you can call from Python can be under test. Suppose you have a payment gateway with a contractual success rate — register the invocation once:

```python
# mavai-bindings.py — discovered beside the contract file and imported
# automatically, exactly as mavai-services.yaml is discovered
from baseltest.declarative import binding
from my_app import gateway

@binding("payment-gateway")
def charge(card_token: str) -> str:
    return gateway.charge(card_token).status_line()
```

```yaml
format: mavai-contract/1
contract: payment-gateway-meets-sla
service: payment-gateway
inputs: ["tok-visa-4242", "tok-mc-5100"]
criteria:
  - name: transaction-succeeds
    threshold: 0.99
    threshold-origin: sla
    contract-ref: "Payment Provider SLA v2.0 §4.1"
    contains: "SUCCESS"
```

A declined charge is a *response* (the criterion judges it); only genuine defects — the gateway unreachable, a bug — abort the run. (Registering from any other module you import before an API-driven run works too; `mavai-bindings.py` is simply the convention the CLI discovers.) The `threshold-origin` lines are optional provenance: the file records not just the bar, but where the bar comes from.

### When the service's identity lives partly outside the code

A binding's name says *which* service; it cannot say which version of the world the service ran under — the model behind an internal endpoint, a prompt-template revision, the content of a rules file the code loads. Declare those as **covariates** and they become part of the baseline's identity:

```python
@binding(
    "payment-gateway",
    covariates={
        "gateway-api": gateway.api_version(),
        "routing-rules": routing_rules_fingerprint(),
    },
)
def charge(card_token: str) -> str:
    return gateway.charge(card_token).status_line()
```

`basel measure` records the resolved values in the baseline artefact's provenance. A later `basel test` resolves them afresh — the bindings file is imported on every invocation — and a mismatch is refused with the drifted key named, never judged silently against evidence measured under a different identity. Keys the framework writes into provenance itself (`binding`, `runMode`, `serviceType`, `taskFile`, `taskFormat`) are reserved and refused at registration. The [`rule-driven-service` example](../examples/README.md) walks the full loop: measure, drift, refusal, re-measure.

### Configuring your own service: types, factories, and explorations

`type: language-model` is not special — it is simply a built-in **service type**. Your own code joins the same registry as a configurable type by registering a *factory* whose signature is the configuration schema:

```python
from baseltest.declarative import binding_factory

@binding_factory("gateway", covariates={"routing-rules": rules_fingerprint()})
def gateway(region: str, retries: int = 0) -> Callable[[str], str]:
    client = build_client(region=region, retries=retries)
    return lambda card_token: client.charge(card_token).status_line()
```

```yaml
# mavai-services.yaml
format: mavai-services/1
services:
  payment-gateway:
    type: gateway
    configuration: {region: eu-central, retries: 0}
    explorations:
      - region: us-east
```

Kebab-case YAML keys map to the factory's snake_case parameters; parameters with defaults are the optional keys; annotations (`str`, `int`, `float`, `bool`) are checked. A services-file entry that does not fit the signature — unknown key, missing required one, wrong type — is refused at load time with the signature in the message. `basel explore` then runs your code's configuration grid exactly as it runs a language model's: one descriptive artefact per grid point, factor-named files, the same diff workflow and comparison report. `test` and `measure` run the baseline `configuration:`, and its keys join the covariates in the drift-checked identity. Factories run at contract-load time (validation constructs the per-sample callable before any sample), so keep them cheap and side-effect-light.

Inputs are typed the same way: an `inputs:` entry may be a scalar or a flat list of scalars, splatted as the binding's positional arguments — `["Basel", 3, true]` calls `forecast(city: str, days: int, metric: bool)`. Arity is always checked against the binding's signature before any sample runs; annotated types are checked where declared.

### `basel check`: the compile step

Everything above is validated at load time — and `basel check <contract>` runs exactly those validations with zero samples: the contract file, the services file against every factory signature (baseline and each exploration entry), the service reference's resolution, and every input against the per-sample callable's signature. Exit 0 prints one `ok:` line per validated fact; exit 2 carries the same refusal a run would give. Put it in your editor loop and CI: a configuration defect should never cost a sample, let alone a paid one.

## Measuring without judging

A file with no thresholds at all cannot be tested — `basel test` refuses it, telling you so — but it measures perfectly well: `basel measure --samples N` reports every criterion as an honest characterisation, never dressed up as a verdict, and persists the baseline artefact.

## The latency dimension

Reliability has a second axis: not just *whether* the service answers correctly, but *how long* the correct answers take. A contract may assert a `latency:` block — per-percentile upper bounds judged over the durations of **passing** samples only (the timing of wrong answers does not characterise the correct path), gating the verdict by conjunction with the functional criteria: a test passes only when both dimensions do. Two shapes, mutually exclusive:

```yaml
latency:                 # explicit: SLA-style ceilings, in milliseconds
  p50: 800
  p95: 2500
  threshold-origin: sla                  # optional provenance, as on criteria
  contract-ref: "Acme SLA v3.2 §4.2"
```

```yaml
latency:                 # empirical: no worse than measured
  empirical: [p50, p95]
  confidence: 0.95                       # optional; the derivation confidence
```

An **explicit** ceiling is your declared requirement, compared directly: the observed percentile (nearest-rank, over passing samples) passes at or below it. An **empirical** declaration derives its bounds from the matching measured baseline's recorded latency profile at test time, using an exact distribution-free upper confidence bound — the latency analogue of the functional *no worse than measured* bar, and like it, statistically honest about sample size: the bound derived from a small baseline is simply looser. The verdict line names the derivation (`bound is the baseline's 35th of 56 sorted latencies`), and the verdict record carries it.

The framework refuses up front — before any invocation, exit 2 — what can never be judged: a percentile the planned sample count cannot estimate (the median needs 5 passing samples, p90 needs 10, p95 needs 20, p99 needs 100), an empirical declaration with no matching baseline (or one measured before latency recording existed — re-measure), and a requested confidence the baseline's size cannot support a bound at (the refusal names the required baseline size). When a run's *passing* count falls below a percentile's minimum only at evaluation time — a flaky service under a small budget — the latency dimension is INCONCLUSIVE rather than judged, and the run exits 3: no assertion can rest on it. Measure and explore runs never judge a latency block; they record the latency profile the empirical bounds derive from.

## Exploring configurations

Before you measure or test a configuration seriously, you often want to know *which* configuration deserves it — does a lower temperature help? a different model? The third verb answers that cheaply. In the services file, the `configuration:` block is the baseline; an `explorations:` section lists the variants, each entry declaring only what deviates from it:

```yaml
format: mavai-services/1
services:
  basket-builder:
    type: language-model
    configuration:                 # the baseline — what measure and test run
      system-prompt: "You translate shopping instructions into a JSON basket."
      model: gpt-4o-mini
      temperature: 0.2
    explorations:                  # each entry: the baseline with these values replaced
      - temperature: 0.0
      - temperature: 0.7
      - model: gpt-4o
        temperature: 0.7
```

The per-configuration count is a pure cost decision of yours, and small counts are the point: the default is 5, `--samples-per-config` sizes it, and baseltest never complains about a low one. Run:

```bash
basel explore basket-builder.yaml
```

Every configuration in the grid — the baseline included — runs like a miniature measure experiment, and each writes one YAML artefact into `_baseltest/explorations/{contract}/`, named after the factor values that distinguish it (`model-gpt-4o-mini_temperature-0.0.yaml`, …). The artefacts are **descriptive only** — observed rates, per-criterion counts, failure reasons, a gated latency summary, and a per-sample result projection carrying each response verbatim; no bounds, no thresholds, no verdicts (a declared `threshold:` in the contract file is simply not consulted). Triage, not judgement: the core move is

```bash
diff _baseltest/explorations/basket-builder-returns-valid-baskets/model-gpt-4o-mini_temperature-0.{0,7}.yaml
```

then promote the winner by folding its values into the `configuration:` block, run `basel measure`, and test forever after. Promotion is safe by construction: an existing baseline was measured under the old configuration, so the next `test` names the drift and refuses to judge against stale evidence until you re-measure. `test` and `measure` never read the `explorations:` section — the baseline is always what they run — and tidying the section (reordering, reformatting, removing it) never invalidates a baseline. Two entries that resolve to the same configuration are refused at load time, as is an entry that merely restates the baseline; explore requires a service declared in the services file — a bare `@binding` carries no configuration grid, but a `@binding_factory` type with a services-file entry explores exactly like a language model does (see *Configuring your own service* above).

## Optimising a configuration

Explore characterises a handful of configurations you can enumerate. Sometimes the question is a *search* instead: which temperature, which system prompt? The `optimize` verb answers that with the family's Optimize experiment — an iterative walk through the configuration space, scored per iteration, abandoned as soon as it stops paying. Its place in the workflow: **explore** finds the promising region, **optimize** hones within it, **measure** locks the winner in as a baseline, **test** asserts against it forever after.

Optimisations live beside explorations in the services file, and like them are invisible to `test` and `measure`:

```yaml
    optimizations:
      - id: prompt-tuning              # names the run and its artefact
        stepper: prompt-engineer       # a meta-LLM proposes each next prompt
        stepper-config: {model: gpt-4o}
        max-iterations: 5
        no-improvement-window: 2       # stop after 2 iterations without improvement

      - id: temperature-honing         # noise-aware, coarse-to-fine grid search
        stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.25, min-step: 0.05}
        initial: {temperature: 0.0}
        max-iterations: 20
```

Run one entry by name — with several declared, an unnamed selection is refused with the ids listed, never guessed (each entry is an independent, potentially expensive experiment); `--all` opts into running every entry, and a lone entry runs without a name:

```bash
basel optimize basket-builder.yaml temperature-honing --samples-per-iteration 10
```

**Iteration 0 is the baseline `configuration:` with the `initial:` overrides applied; no `initial:` means iteration 0 is the baseline itself.** The overlay is partial, with exactly an exploration entry's merge semantics, and an overlay that merely restates the baseline is refused. The two entries above illustrate both sides of the default: `prompt-tuning` omits `initial:` because iteration 0 should score the *incumbent* prompt, giving the meta-LLM's first suggestion a measured reference point; `temperature-honing` provides it because the walk should start at the interval's edge, not wherever the baseline happens to sit.

Each iteration runs like a miniature measure with explore's descriptive posture — no thresholds consulted, no verdict rendered — and is scored. The default scorer is the iteration's observed pass rate, maximised; declare `scorer:` (a name registered with `@scorer` in `mavai-bindings.py`) and `objective: minimize` to override. The **stepper** then proposes the next configuration: it receives the whole current configuration mapping plus the run's context (full history with per-criterion failure breakdowns and exemplars, the best so far, the remaining iteration budget) and returns the whole next configuration — or `None` to stop. The run ends at `max-iterations`, on the `no-improvement-window` plateau, or when the stepper stops.

**Measuring a configuration twice is legitimate — and sometimes exactly right.** A stochastic service's score is noisy: 7 of 10 on one visit and 9 of 10 on the next are the *same* configuration seen through sampling noise. A stepper is therefore free to propose a configuration the run has already measured — the framework runs it, notes on the console that the revisit is deliberate, and records every visit in the history (the artefact never collapses them). A noise-aware stepper exploits this: repeated visits pool into more evidence per configuration, so its comparisons rest on counts, not on whichever single visit happened to land lucky. If you see the same factors appear twice in a trajectory, that is the optimiser buying confidence, not going in circles — the iteration cap always bounds the spend.

Three steppers ship built in. `prompt-engineer` sends the previous iteration's prompt, score, and failure breakdown to a meta-LLM and treats the response as the next `system-prompt` (`target-key:` retargets it); its meta model defaults to the optimized service's own `provider:`/`model:`, so the credentials you already exported cover it and no vendor is silently pinned. `linear-sweep` walks one numeric key in fixed `step:` increments to `stop:` — a fixed grid you want fully characterised is an *exploration*; what earns the sweep a place here is the plateau window abandoning the walk early. `refining-grid` is the noise-aware search for one numeric key: it measures every value on a coarse grid over `[lo, hi]`, pools the evidence per value across visits, then narrows to the leading value's neighbourhood at half the `step:` and repeats down to `min-step:` — a candidate is eliminated only when its uncertainty interval can no longer carry a meaningful advantage (`min-improvement:`, default 0.02) over the leader's, never because of a single bad round — and finally re-measures the two finalists in independent confirmation epochs (`confirmation-epochs:`, default 2) before selecting, preferring the lower value on a practical tie (`prefer: high` flips that). Its selection, finalist standings, and stopping reason are recorded in the artefact's `stepper:` block; note that the artefact's `convergence:` block still names the best *single iteration* by score, while a noise-aware stepper's own selection rests on evidence pooled across visits — when they differ, trust the pooled selection. Your own steppers register in `mavai-bindings.py` as factories whose parameters are the entry's `stepper-config:` schema, with any search state held in the factory's closure:

```python
from baseltest.declarative import stepper

@stepper("halve-until", configuration_keys=("key",))
def halve_until(key: str, floor: float):
    def step(current, ctx):
        value = current[key] / 2
        return {**current, key: value} if value >= floor else None
    return step
```

Everything checkable without a sample is checked at load time — unknown keys, an unresolvable stepper or scorer, a `stepper-config:` that does not fit the factory's signature, a stepper targeting a configuration key that does not exist, a no-op `initial:` — and `basel check` runs all of it for zero samples. Mid-run, a stepper that proposes an invalid configuration fails the run with the iteration and offence named.

One YAML artefact per run lands in `_baseltest/optimizations/{contract}/{id}.yaml`, in the family's canonical `mavai-optimize-1` schema: the **full iteration history** — every configuration tried, its score, per-criterion counts, failure distribution, gated latency, per-sample projection — plus a convergence block naming the best iteration and a record of which stepper drove the search. Descriptive throughout: an optimize run makes no inferential claim about the optimum. The console prints the trajectory and the best factors; promotion is the same manual move as explore's — fold the winning values into `configuration:`, `basel measure`, and the drift check keeps you honest along the way.

## The verdict record

Every `test` run also writes its results as a **verdict record** — XML in the mavai family's canonical schema (defined by punit, namespace `http://mavai.org/verdict/1.0`), into `_baseltest/verdicts/` by default (`--verdict-dir` to move it, `--no-verdict-xml` to switch it off). The record carries the full decomposition: per-criterion verdicts with counts and thresholds, the composite, failure-reason clauses, threshold provenance (including the baseline artefact an empirical bar came from), and the run's execution facts. Because every framework in the family emits the same schema, the same downstream tooling reads them all.

## HTML reports

Every run persists its artefacts, so reporting never requires re-execution: `basel report test` renders one self-contained HTML page from the verdict records under `_baseltest/verdicts/`. The report lands in `_baseltest/reports/` (`--out` relocates it), opens offline in any browser (all CSS inline, no JavaScript, no external assets), and shares the mavai family's report look, so a basel report and a punit report read as siblings. With nothing to render the verb aborts with a friendly pointer (exit 2); `basel report measure` is reserved — no measure report type exists in the family yet.

Prefer the report in one step? `--html-report <path>` on `test` renders the same report from the just-persisted verdict record as part of the run — one rendering path, so the inline report and a later `basel report test` over the same run are identical. The flag never changes the verb's exit code.

Exploration comparison reports are the family's shared tool's job: baseltest emits the canonical `mavai-explore-1` artefacts under `_baseltest/explorations/`, and the [mavai](https://github.com/mavai-org/mavai/releases) tool renders the comparison page from them — `mavai explore _baseltest/explorations -o report.html`. Because every framework in the family emits the same artefact schema, one tool renders them all.

## Exit codes

The return code is the machine-readable half of the honest-output story — CI reads it, and each number means one thing:

| Code | Meaning |
|---|---|
| `0` | Success. `test`: every judged criterion passed. `measure`: recorded (and, with `--assert`, every declared bar met). `explore`: every configuration explored and its artefact persisted (an exploration cannot fail — it judges nothing). `optimize`: every selected run completed and its artefact persisted (like explore, it judges nothing). |
| `1` | **Judgement failure.** `test`: the composite verdict is FAIL. `measure --assert`: a declared bar was not met (the baseline is still on disk — recording happens before assertion). |
| `2` | **Refusal.** The run never invoked the service: malformed contract file, unresolvable binding, nothing to test, a test whose sample count cannot support its bars (functional or latency), an empirical latency declaration with no usable baseline or a confidence its baseline cannot support, a silently derived n above the 100-sample gate, a measure without `--samples`, an explore over a service with no services-file grid, an optimize selection left ambiguous (or over a service with no `optimizations:` section), a stepper mid-run proposing an invalid configuration, a `basel check` join failure, contradictory sizing flags (`--samples` with `--tolerate` or `--power`), unclaimed empirical tolerances with no terminal to ask on, an over-reaching tolerance in automation without `--force`, or any declined confirmation. |
| `3` | **Unsupportable assertion.** `measure --assert`: the sample size could never have supported a declared bar. `test`: too few samples *passed* for an asserted latency percentile to be estimated — the composite is INCONCLUSIVE. Either way, no assertion can rest on the evidence, in either direction. |

`0` is the only success; any non-zero fails a CI step. The distinctions matter for scripting: `1` means the service fell short, `2` means the run was never valid, `3` means the run was too small to know.

## Ready-to-run examples

The [`examples/`](../examples/README.md) directory has both paths ready to run: a **simulated stochastic service** that works offline with zero setup (see the statistics move between runs while the verdict logic holds still), and the **basket-builder** against a real model.

## When you outgrow the files

The contract file is a front-end: baseltest turns it into a real service contract evaluated by the same engine a hand-written one uses. When you need more than the file can say, graduate — take direct authorship of that contract in Python (`baseltest.contract`). You keep everything; nothing migrates.
