# Examples

Ready-to-run declarative authoring, from zero.

## `simulated-service/` — runs offline, no setup at all

Three files, three roles:

| File | Role |
|---|---|
| `mavai-bindings.py` | **The service itself** — the code invoked once per sample. Here it *simulates* a stochastic service (true success rate ≈ 0.9) so the example runs offline; in real use this is where your API/LLM call lives. Discovered and imported automatically, like pytest's `conftest.py`. |
| `task.yaml` | **The test posture** — declares a threshold (0.8), so the run renders a verdict: PASS only if the evidence supports, at 95% confidence, that the *true* rate clears the bar. |
| `measure.yaml` | **The observation posture** — same service, same criterion, *no threshold*: nothing to judge against, so the run reports what is (rate, variance), labelled as a measurement, and persists a baseline artefact into `baselines/` — the durable record of how the service behaved. |

The filenames are just labels — what decides a run's nature is the file's *content*: `kind: measure` persists a baseline; a declared `threshold:` makes a test (verdict, nothing persisted); neither makes a bare observation (characterisation only, no files left behind).

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
baseltest run task.yaml       # test posture: verdict, nothing persisted
baseltest run measure.yaml    # measure posture: characterisation + baseline artefact
```

Only the measure posture persists a baseline — a test run produces a verdict and writes nothing, by design.

The task declares `intent: smoke` with 30 samples so a first try is quick and cheap; for a statistically enforced verdict, remove that line and raise `samples` (baseltest will tell you the minimum that supports the threshold — or delete `samples:` and it derives the minimum for you).
