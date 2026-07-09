# Getting started with baseltest

baseltest tests services that don't behave the same way twice — LLM-backed services above all. You declare what a good response looks like and what pass rate you require; baseltest runs the service repeatedly and gives you a verdict backed by real statistics, not a green tick over one lucky sample.

For your first test you write **two small files and no Python**.

## Setup

```bash
# Python 3.11+ required
pip install "baseltest[declarative]"

export MAVAI_LLM_API_KEY="..."   # or your vendor's usual variable, e.g. OPENAI_API_KEY
```

baseltest ships basic adapters for `openai`, `anthropic`, `mistral`, `ollama` (local, no key), and `apertus` (the fully open Swiss model, served via the Public AI utility) — declare one as `provider:` in the service configuration below. Prefer your own OpenAI-compatible endpoint (vLLM, a gateway)? Omit `provider:` and set `MAVAI_LLM_ENDPOINT` instead. Credentials live in the environment only — they never appear in either file. The adapters are deliberately plain: one request per sample, no retries and no caching, because a silently retried failure would bias the very rate under test.

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
baseltest test basket-builder.yaml
```

```
n = 52 (derived: criterion response-is-a-valid-basket's threshold 0.95 requires at least 52 samples)
contract basket-builder-returns-valid-baskets: PASS
  criterion response-is-a-valid-basket: PASS
    52 of 52 responses met expectations
    observed rate 1.0000; we can be 95% confident the true rate is at least 0.9505 — clears your 0.95 threshold
```

That last line is the point of baseltest: the verdict is not "100% ≥ 95%". It is a claim about the *true* rate, at a stated confidence, computed from a Wilson lower bound — a high observed rate over too few samples would honestly fail. Notice what the derived minimum means: at n = 52, only a perfect run can clear a 0.95 bar. A larger `--samples` buys slack — at n = 100, two failures still pass (the lower bound of 98/100 is 0.9530). Add `--html-report report.html` for a self-contained summary page.

The first line is the **run-plan line**: every run opens by stating its n and where the value came from, so no sample ever runs on a number you can't see. The contract file carries the **claim** (criteria, thresholds, intent); the invocation carries the **budget**. With no flag, a test runs at the *derived minimum* — the smallest n that can support every declared bar at its confidence, computed from the thresholds themselves. One guard applies to that derivation: if the minimum exceeds **100 samples** (roughly, any bar above 0.96), the run is refused before a single invocation, naming the number to type — `--samples N` runs it deliberately at any size, and `intent: smoke` gives a cheap pass that renders no statistical verdict. The gate binds only the number nobody typed: an explicit flag of any size sails through (and is still feasibility-checked, so a flag too small for the bar is refused too).

`--samples N` works on `test` and `measure` alike, and the confidence bound is honestly computed at the size actually run — a cheap 50-sample check is still a statistically meaningful one.

**`test` judges; `measure` records.** The same file, run as `baseltest measure basket-builder.yaml --samples 1000`, records *every* criterion (rate, variance, failure distribution) — a declared bar is noted against the evidence as *met* or *not met*, a recorded fact rather than a verdict, and the run always exits successfully — and always persists a **baseline artefact** into `_baseltest/baselines/`: the durable record of what was observed, under exactly which service configuration. When at least one sample passed, the baseline also records the run's **latency profile** — the gated percentiles (p50/p90/p95/p99, each present only when the passing-sample count can support it) and the full ascending vector of passing-sample durations, the raw material from which a later consumer derives latency bounds at its own sample size and confidence; only passing samples contribute, because the timing of incorrect behaviour does not characterise the correct path. (Everything baseltest generates lives under the single `_baseltest/` directory — one `.gitignore` line, one `rm -rf` for a clean slate.) A test run persists no baseline: its product is the verdict, written into `_baseltest/verdicts/` as the verdict record described below. `measure` is the one verb with no default n — a measurement's budget is an experimental-design decision, so it must be typed: `--samples 1000` is a solid baseline-grade count, and a smaller deliberate budget is legitimate (an empirical bar derived from a smaller baseline simply widens honestly). A criterion with no `threshold:` is an **empirical** criterion — its bar comes from evidence rather than declaration. Before any baseline exists, `test` skips it with a one-line indicator; but once you have run `baseltest measure`, the next `test` finds the baseline and judges the empirical criterion against it — *no worse than measured*, the bar derived from the baseline's recorded evidence at the test's own sample size, the verdict line naming the artefact it judged against:

```
criterion spirits-stay-polite: PASS
  observed rate 1.0000; we can be 95% confident the true rate is at least 0.9867
  — clears your 0.9654 threshold (empirical, fortune-teller-…-b44846234567.yaml)
```

The workflow is **measure once, test forever after** — and the baseline only matches if it measured *the same thing*: same contract, same inputs, same service configuration. Change the model or the system prompt and the test tells you the baseline no longer applies (naming the differing settings) instead of quietly judging against stale evidence.

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

## Measuring without judging

A file with no thresholds at all cannot be tested — `baseltest test` refuses it, telling you so — but it measures perfectly well: `baseltest measure --samples N` reports every criterion as an honest characterisation, never dressed up as a verdict, and persists the baseline artefact.

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
baseltest explore basket-builder.yaml
```

Every configuration in the grid — the baseline included — runs like a miniature measure experiment, and each writes one YAML artefact into `_baseltest/explorations/{contract}/`, named after the factor values that distinguish it (`model-gpt-4o-mini_temperature-0.0.yaml`, …). The artefacts are **descriptive only** — observed rates, per-criterion counts, failure reasons, a gated latency summary, and a per-sample result projection carrying each response verbatim; no bounds, no thresholds, no verdicts (a declared `threshold:` in the contract file is simply not consulted). Triage, not judgement: the core move is

```bash
diff _baseltest/explorations/basket-builder-returns-valid-baskets/model-gpt-4o-mini_temperature-0.{0,7}.yaml
```

then promote the winner by folding its values into the `configuration:` block, run `baseltest measure`, and test forever after. Promotion is safe by construction: an existing baseline was measured under the old configuration, so the next `test` names the drift and refuses to judge against stale evidence until you re-measure. `test` and `measure` never read the `explorations:` section — the baseline is always what they run — and tidying the section (reordering, reformatting, removing it) never invalidates a baseline. Two entries that resolve to the same configuration are refused at load time, as is an entry that merely restates the baseline; explore currently requires a service declared in the services file (a code-registered `@binding` carries no configuration grid to explore).

## The verdict record

Every `test` run also writes its results as a **verdict record** — XML in the mavai family's canonical schema (defined by punit, namespace `http://mavai.org/verdict/1.0`), into `_baseltest/verdicts/` by default (`--verdict-dir` to move it, `--no-verdict-xml` to switch it off). The record carries the full decomposition: per-criterion verdicts with counts and thresholds, the composite, failure-reason clauses, threshold provenance (including the baseline artefact an empirical bar came from), and the run's execution facts. Because every framework in the family emits the same schema, the same downstream tooling reads them all.

## Exit codes

The return code is the machine-readable half of the honest-output story — CI reads it, and each number means one thing:

| Code | Meaning |
|---|---|
| `0` | Success. `test`: every judged criterion passed. `measure`: recorded (and, with `--assert`, every declared bar met). `explore`: every configuration explored and its artefact persisted (an exploration cannot fail — it judges nothing). |
| `1` | **Judgement failure.** `test`: the composite verdict is FAIL. `measure --assert`: a declared bar was not met (the baseline is still on disk — recording happens before assertion). |
| `2` | **Refusal.** The run never invoked the service: malformed contract file, unresolvable binding, nothing to test, a test whose sample count cannot support its bars, a silently derived n above the 100-sample gate, a measure without `--samples`, or an explore over a code-registered binding. |
| `3` | **Unsupportable assertion.** `measure --assert` only: the sample size could never have supported a declared bar — no assertion can rest on the evidence, in either direction. Recorded and persisted all the same. |

`0` is the only success; any non-zero fails a CI step. The distinctions matter for scripting: `1` means the service fell short, `2` means the run was never valid, `3` means the run was too small to know.

## Ready-to-run examples

The [`examples/`](../examples/README.md) directory has both paths ready to run: a **simulated stochastic service** that works offline with zero setup (see the statistics move between runs while the verdict logic holds still), and the **basket-builder** against a real model.

## When you outgrow the files

The contract file is a front-end: baseltest turns it into a real service contract evaluated by the same engine a hand-written one uses. When you need more than the file can say, graduate — take direct authorship of that contract in Python (`baseltest.contract`). You keep everything; nothing migrates.
