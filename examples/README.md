# Examples

Ready-to-run declarative authoring, from zero. Each folder holds **one task file**; what a run does is the verb you invoke it with:

- `baseltest test task.yaml` — a probabilistic test: the thresholded criteria are judged (a criterion without a bar is skipped, with a notice). Produces a verdict; persists nothing.
- `baseltest measure task.yaml` — a measure experiment: **every** criterion is recorded (thresholded ones are judged too), and a baseline artefact is persisted into `baselines/` — the durable record of what was observed.

## `simulated-service/` — runs offline, no setup at all

Two files, two roles:

| File | Role |
|---|---|
| `mavai-bindings.py` | **The service itself** — the code invoked once per sample. Here it *simulates* a stochastic service (true success rate ≈ 0.9) so the example runs offline; in real use this is where your API/LLM call lives. Discovered and imported automatically, like pytest's `conftest.py`. |
| `task.yaml` | **The declaration** — the service, the criteria (one with a bar, one without), the inputs. Posture-free: the verb decides what happens. |

```bash
pip install "baseltest[declarative]"
cd examples/simulated-service

baseltest test task.yaml       # verdict against the 0.8 threshold
baseltest measure task.yaml    # everything recorded, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence, not a comparison of one lucky sample.

## `language-model/` — a real model, two files, no Python

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its response parsed as JSON (the `transforms:` block declares the `basket` view) and judged structurally — every item named, every quantity positive, plus an input-specific expectation (eggs in the egg order). Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
baseltest test task.yaml       # test posture: verdict, nothing persisted
baseltest measure task.yaml    # measure posture: characterisation + baseline artefact
```

The task declares `intent: smoke` with 30 samples so a first try is quick and cheap; for a statistically enforced verdict, remove that line and raise `samples` (baseltest will tell you the minimum that supports the threshold — or delete `samples:` and it derives the minimum for you).
