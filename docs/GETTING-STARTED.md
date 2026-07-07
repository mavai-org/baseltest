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

This file says what you are testing: the inputs, what a good response looks like, and - optionally - the bar it must clear.

```yaml
format: mavai-task/1
task: basket-builder-returns-valid-baskets
service: basket-builder
samples: 100
inputs:
  - "two bottles of milk and a loaf of bread"
  - "add three apples"
  - "a dozen eggs, please"
criteria:
  - name: response-is-a-valid-basket
    threshold: 0.95
    transform: json
    postconditions:
      - path: "$.items[*].name"
        matches: "."
```

Reading it aloud: invoke `basket-builder` 100 times, cycling through the three instructions; each response must parse as JSON and every selected item name must be non-empty (an empty selection fails the trial too — a basket with no items is not a valid basket); require a 95% pass rate.

## Run it

```bash
baseltest run task.yaml
```

```
task basket-builder-returns-valid-baskets: PASS
  criterion response-is-a-valid-basket: PASS
    98 of 100 responses met expectations
    observed rate 0.9800; we can be 95% confident the true rate is at least 0.9530 — clears your 0.95 threshold
```

That last line is the point of baseltest: the verdict is not "98% ≥ 95%". It is a claim about the *true* rate, at a stated confidence, computed from a Wilson lower bound — a 98% observation over too few samples would honestly fail. If you declare a threshold your sample count cannot support, baseltest refuses to run and tells you the minimum that would work (or omit `samples:` entirely and baseltest derives that minimum for you). Add `--html-report report.html` for a self-contained summary page.

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

Drop the `threshold` and the run becomes an honest measurement — a characterisation, never dressed up as a verdict:

```
task basket-builder-returns-valid-baskets: OBSERVATION (no threshold declared — this is a measurement, not a verdict)
```

With `kind: measure`, the run also persists a baseline artefact: the durable record of what was observed, under exactly which service configuration.

## Ready-to-run examples

The [`examples/`](../examples/README.md) directory has both paths ready to run: a **simulated stochastic service** that works offline with zero setup (see the statistics move between runs while the verdict logic holds still), and the **basket-builder** against a real model.

## When you outgrow the files

The task file is a front-end: baseltest turns it into a real service contract evaluated by the same engine a hand-written one uses. When you need more than the file can say, graduate — take direct authorship of that contract in Python (`baseltest.contract`). You keep everything; nothing migrates.
