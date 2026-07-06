# Examples

Ready-to-run declarative authoring, from zero.

## `simulated-service/` — runs offline, no setup at all

A simulated stochastic "fortune teller" (true success rate ≈ 0.9) lives in `mavai-bindings.py`, which the runner discovers and imports automatically, exactly as it discovers `mavai-services.yaml`.

```bash
pip install "baseltest[declarative]"
cd examples/simulated-service

baseltest run task.yaml       # a probabilistic test: verdict against a 0.8 threshold
baseltest run measure.yaml    # the same service measured: no verdict, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence, not a comparison of one lucky sample.

## `language-model/` — a real model, two files, no Python

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its output shape guided by a response schema. Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
baseltest run task.yaml
```

The task declares `intent: smoke` with 30 samples so a first try is quick and cheap; for a statistically enforced verdict, remove that line and raise `samples` (baseltest will tell you the minimum that supports the threshold — or delete `samples:` and it derives the minimum for you).
