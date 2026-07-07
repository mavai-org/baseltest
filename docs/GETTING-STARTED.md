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
        properties:
          items:
            type: array
            items:
              type: object
              properties:
                name: { type: string }
                quantity: { type: integer }
        required: [items]
```

The `response-schema` tells the model — through the provider's structured-output mechanism — exactly what shape to return, which is often the single strongest lever on an LLM service's pass rate. It is part of the service's identity like every other parameter. (Not every provider supports it; baseltest refuses up front rather than quietly dropping it, because dropping it would change what you are measuring.)

The schema above is written in YAML style, but only the *file* is YAML — on the wire, baseltest serialises it to exactly the JSON the provider APIs expect. And since YAML is a superset of JSON, you can also paste a JSON Schema in verbatim; both forms parse to the identical structure:

```yaml
      response-schema: {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"]
      }
```

Everything in `configuration:` is part of the service's identity, and baseltest records the resolved values (including the model, even when it came from the environment) in every result — so you always know exactly what was measured.

## File 2: the task (`task.yaml`)

This file says what you are examining: the inputs, what a good response looks like, and - optionally - the bar it must clear. It is deliberately **posture-free**: whether a run judges or measures is decided by how you invoke it, not by the file.

```yaml
format: mavai-task/1
task: basket-builder-returns-valid-baskets
service: basket-builder
samples: 100

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

The file reads top to bottom as *machinery, rules, cases*. The `transforms:` block declares a **view**: a named transformation of the response, computed at most once per response and shared by every check that names it via `in:`. A check without `in:` judges the raw response text (`raw` is the reserved name for it, should you want to be explicit). Reading the whole file aloud: invoke `basket-builder` 100 times, cycling through the three instructions; each response must parse as JSON, every item must carry a real name, every quantity must be a positive integer — and the egg order must actually contain eggs. Because a `path` check fails the trial when it selects nothing, a basket with no items fails too; and a `path` check judges **every** value it selects: one bad quantity among five items fails that trial.

## Run it

```bash
baseltest test task.yaml
```

```
task basket-builder-returns-valid-baskets: PASS
  criterion response-is-a-valid-basket: PASS
    98 of 100 responses met expectations
    observed rate 0.9800; we can be 95% confident the true rate is at least 0.9530 — clears your 0.95 threshold
```

That last line is the point of baseltest: the verdict is not "98% ≥ 95%". It is a claim about the *true* rate, at a stated confidence, computed from a Wilson lower bound — a 98% observation over too few samples would honestly fail. If you declare a threshold your sample count cannot support, baseltest refuses to run and tells you the minimum that would work (or omit `samples:` entirely and baseltest derives that minimum for you). Add `--html-report report.html` for a self-contained summary page.

The verb is half the story. **`test` judges; `measure` records.** The same file, run as `baseltest measure task.yaml`, records *every* criterion (rate, variance, failure distribution) — a declared bar is noted against the evidence as *met* or *not met*, a recorded fact rather than a verdict, and the run always exits successfully — and always persists a **baseline artefact** into `baselines/`: the durable record of what was observed, under exactly which service configuration. A test run persists nothing: its product is the verdict. A criterion with no `threshold:` is an **empirical** criterion — its bar comes from evidence rather than declaration: once a matching baseline exists, `test` will judge it against that baseline like any other (arriving in baseltest shortly); until then `test` skips it with a one-line indicator saying it needs a baseline first.

## Testing your own (non-LLM) service

Anything you can call from Python can be under test. Suppose you have a payment gateway with a contractual success rate — register the invocation once:

```python
# mavai-bindings.py — discovered beside the task file and imported
# automatically, exactly as mavai-services.yaml is discovered
from baseltest.declarative import binding
from my_app import gateway

@binding("payment-gateway")
def charge(card_token: str) -> str:
    return gateway.charge(card_token).status_line()
```

```yaml
format: mavai-task/1
task: payment-gateway-meets-sla
service: payment-gateway
samples: 1000
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

A file with no thresholds at all cannot be tested — `baseltest test` refuses it, telling you so — but it measures perfectly well: `baseltest measure` reports every criterion as an honest characterisation, never dressed up as a verdict, and persists the baseline artefact. Declare `samples:` explicitly in that case (with no bar there is no feasibility arithmetic to derive one from).

## Exit codes

The return code is the machine-readable half of the honest-output story — CI reads it, and each number means one thing:

| Code | Meaning |
|---|---|
| `0` | Success. `test`: every judged criterion passed. `measure`: recorded (and, with `--assert`, every declared bar met). |
| `1` | **Judgement failure.** `test`: the composite verdict is FAIL. `measure --assert`: a declared bar was not met (the baseline is still on disk — recording happens before assertion). |
| `2` | **Refusal.** The run never invoked the service: malformed task file, unresolvable binding, nothing to test, or a test whose sample count cannot support its bars. |
| `3` | **Unsupportable assertion.** `measure --assert` only: the sample size could never have supported a declared bar — no assertion can rest on the evidence, in either direction. Recorded and persisted all the same. |

`0` is the only success; any non-zero fails a CI step. The distinctions matter for scripting: `1` means the service fell short, `2` means the run was never valid, `3` means the run was too small to know.

## Ready-to-run examples

The [`examples/`](../examples/README.md) directory has both paths ready to run: a **simulated stochastic service** that works offline with zero setup (see the statistics move between runs while the verdict logic holds still), and the **basket-builder** against a real model.

## When you outgrow the files

The task file is a front-end: baseltest turns it into a real service contract evaluated by the same engine a hand-written one uses. When you need more than the file can say, graduate — take direct authorship of that contract in Python (`baseltest.contract`). You keep everything; nothing migrates.
