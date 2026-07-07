# Examples

Ready-to-run declarative authoring, from zero. Each folder holds **one contract file**; what a run does is the verb you invoke it with:

- `baseltest test contract.yaml` — a probabilistic test: the thresholded criteria are judged (a criterion without a bar is skipped, with a notice). Produces a verdict, written as a verdict record into `verdicts/`; no baseline is persisted.
- `baseltest measure contract.yaml` — a measure experiment: **every** criterion is recorded (thresholded ones are judged too), and a baseline artefact is persisted into `baselines/` — the durable record of what was observed.

## `simulated-service/` — runs offline, no setup at all

Two files, two roles:

| File | Role |
|---|---|
| `mavai-bindings.py` | **The service itself** — the code invoked once per sample. Here it *simulates* a stochastic service (true success rate ≈ 0.9) so the example runs offline; in real use this is where your API/LLM call lives. Discovered and imported automatically, like pytest's `conftest.py`. |
| `contract.yaml` | **The declaration** — the service, the criteria (one with a bar, one without), the inputs. Posture-free: the verb decides what happens. |

```bash
pip install "baseltest[declarative]"
cd examples/simulated-service

baseltest test contract.yaml       # verdict against the 0.8 threshold
baseltest measure contract.yaml    # everything recorded, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence, not a comparison of one lucky sample.

Then run them **in order** — `measure` first, `test` second — and watch the ratchet: the bar-less `spirits-stay-polite` criterion is skipped by the first test (*requires a baseline*), but after a measure run the next test judges it **against the baseline** — no worse than measured, the artefact named on the verdict line.

## `language-model/` — a real model, two files, no Python

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its response parsed as JSON (the `transforms:` block declares the `basket` view) and judged structurally — every item named, every quantity positive, plus an input-specific expectation (eggs in the egg order). Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
baseltest test contract.yaml       # test posture: verdict (recorded in verdicts/), no baseline
baseltest measure contract.yaml    # measure posture: characterisation + baseline artefact
```

The contract declares `intent: smoke` with 30 samples and a 0.8 bar so a first try is quick, cheap, and *honestly passable* — 30 samples can never support a 0.95 claim, however well the model does, and baseltest refuses to pretend otherwise. To graduate to a production bar: raise `threshold`, remove `intent: smoke`, and either raise `samples` or delete it and let baseltest derive the minimum the bar needs.
