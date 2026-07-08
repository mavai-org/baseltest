# Examples

Ready-to-run declarative authoring, from zero. Each folder holds **one contract file, named for what it tests** — the name is yours, and you keep as many contract files as you have things to test. (The `mavai-*` files beside it are the opposite: fixed, namespaced names the reader discovers automatically — `mavai-services.yaml` for service definitions, `mavai-bindings.py` for code registrations.) What a run does is the verb you invoke it with:

- `baseltest test <contract-file>` — a probabilistic test: the thresholded criteria are judged (a criterion without a bar is skipped, with a notice). Produces a verdict, written as a verdict record into `_baseltest/verdicts/`; no baseline is persisted.
- `baseltest measure <contract-file>` — a measure experiment: **every** criterion is recorded (thresholded ones are judged too), and a baseline artefact is persisted into `_baseltest/baselines/` — the durable record of what was observed.
- `baseltest explore <contract-file>` — an exploration: every configuration in the service's grid (the baseline plus its `explorations:` entries) runs a few samples, and each writes one descriptive artefact into `_baseltest/explorations/` — no verdicts, just the numbers to diff. Requires a service declared in the services file.

Everything a run generates lands under `_baseltest/` — one entry to gitignore, one directory to delete for a clean slate.

## `simulated-service/` — runs offline, no setup at all

Two files, two roles:

| File | Role |
|---|---|
| `mavai-bindings.py` | **The service itself** — the code invoked once per sample. Here it *simulates* a stochastic service (true success rate ≈ 0.9) so the example runs offline; in real use this is where your API/LLM call lives. Discovered and imported automatically, like pytest's `conftest.py`. |
| `fortune-teller.yaml` | **The declaration** — the service, the criteria (one with a bar, one without), the inputs. Posture-free: the verb decides what happens. Freely named, unlike its discovered `mavai-*` neighbour. |

```bash
pip install "baseltest[declarative]"
cd examples/simulated-service

baseltest test fortune-teller.yaml       # verdict against the 0.8 threshold
baseltest measure fortune-teller.yaml    # everything recorded, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence, not a comparison of one lucky sample.

Then run them **in order** — `measure` first, `test` second — and watch the ratchet: the bar-less `spirits-stay-polite` criterion is skipped by the first test (*requires a baseline*), but after a measure run the next test judges it **against the baseline** — no worse than measured, the artefact named on the verdict line.

## `language-model/` — a real model, two files, no Python

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its response parsed as JSON (the `transforms:` block declares the `basket` view) and judged structurally — every item named, every quantity positive, plus an input-specific expectation (eggs in the egg order). Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
baseltest test basket-builder.yaml       # test posture: verdict (recorded in _baseltest/verdicts/), no baseline
baseltest measure basket-builder.yaml    # measure posture: characterisation + baseline artefact
baseltest explore basket-builder.yaml    # explore posture: one descriptive artefact per configuration
```

The contract declares `intent: smoke` with 30 samples and a 0.8 bar so a first try is quick, cheap, and *honestly passable* — 30 samples can never support a 0.95 claim, however well the model does, and baseltest refuses to pretend otherwise. To graduate to a production bar: raise `threshold`, remove `intent: smoke`, and either raise `samples` or delete it and let baseltest derive the minimum the bar needs.

### Compare two models with one explore run

The services file also carries an `explorations:` grid: two temperature variants over the baseline, plus the same job on a different model — [Apertus](https://huggingface.co/swiss-ai/Apertus-70B-Instruct-2509), the fully open Swiss model, served by the [Public AI inference utility](https://publicai.co). `test` and `measure` never read the grid (they run the baseline `configuration:`); `explore` runs every point, a few samples each, and writes one descriptive YAML per configuration. Step by step:

1. **Set both credentials** (each provider uses its own conventional variable):

   ```bash
   export OPENAI_API_KEY=...      # the baseline and temperature entries
   export PUBLICAI_API_KEY=...    # the apertus entry — get one at publicai.co
   ```

   No Public AI key? Delete the apertus entry from `mavai-services.yaml` and the sweep is temperature-only — the steps below work the same.

2. **Run the exploration** (4 configurations × 3 samples — quick and cheap by design; an exploration renders no verdict, so no sample count is ever "too small"):

   ```bash
   baseltest explore basket-builder.yaml
   ```

3. **Read the summary** — one line per configuration, observed rates only — then list the artefacts it wrote:

   ```bash
   ls _baseltest/explorations/basket-builder-returns-valid-baskets/
   # provider-apertus_model-swiss-ai_Apertus-70B-Ins-20d9_temperature-0.2.yaml
   # provider-openai_model-gpt-4o-mini_temperature-0.0.yaml
   # provider-openai_model-gpt-4o-mini_temperature-0.2.yaml
   # provider-openai_model-gpt-4o-mini_temperature-0.7.yaml
   ```

4. **Diff the two models** at the same temperature — the files are built for exactly this: the lines that differ are the factor values and the statistics, nothing else:

   ```bash
   cd _baseltest/explorations/basket-builder-returns-valid-baskets
   diff provider-openai_model-gpt-4o-mini_temperature-0.2.yaml \
        provider-apertus_model-swiss-ai_Apertus-70B-Ins-20d9_temperature-0.2.yaml
   ```

   Each file carries the configuration's factors, observed pass rate, per-criterion counts, and failure reasons — descriptive statistics only, triage rather than judgement.

5. **Promote the winner.** Fold its values into the `configuration:` block, then `baseltest measure` and `baseltest test` as usual. An old baseline measured under the previous configuration no longer matches — the next test names the drift and refuses to judge against stale evidence until you re-measure.

One design note the grid makes visible: the guide's version of this service declares a `response-schema:`, but a grid spanning two providers carries only covariates every provider honours — apertus's hosted endpoint has no structured-output support, and baseltest refuses to silently drop a declared schema rather than quietly change what is being measured. Here the system prompt carries the output shape instead.
