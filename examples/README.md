# Examples

Ready-to-run declarative authoring, from zero. Each folder holds **one contract file, named for what it tests** — the name is yours, and you keep as many contract files as you have things to test. (The `mavai-*` files beside it are the opposite: fixed, namespaced names the reader discovers automatically — `mavai-services.yaml` for service definitions, `mavai-bindings.py` for code registrations.) What a run does is the verb you invoke it with:

- `baseltest test <contract-file>` — a probabilistic test: the thresholded criteria are judged (a criterion without a bar is skipped, with a notice). Produces a verdict, written as a verdict record into `_baseltest/verdicts/`; no baseline is persisted.
- `baseltest measure <contract-file> --samples N` — a measure experiment: **every** criterion is recorded (thresholded ones are judged too), and a baseline artefact is persisted into `_baseltest/baselines/` — the durable record of what was observed. The sample count is required: a measurement's budget is an experimental-design decision (1000 is a solid baseline-grade count; smaller deliberate budgets are legitimate).
- `baseltest explore <contract-file>` — an exploration: every configuration in the service's grid (the baseline plus its `explorations:` entries) runs a few samples (5 by default; `--samples-per-config` to size it), and each writes one descriptive artefact into `_baseltest/explorations/` — no verdicts, just the numbers to diff. Requires a service declared in the services file.

Everything a run generates lands under `_baseltest/` — one entry to gitignore, one directory to delete for a clean slate. Every run opens with a **run-plan line** stating its n and where the value came from (derived from the declared bar, set via a flag, or the verb's default) — no sample ever runs on a number you can't see.

## `simulated-service/` — runs offline, no setup at all

Two files, two roles:

| File                  | Role                                                                                                                                                                                                                                                                              |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mavai-bindings.py`   | **The service itself** — the code invoked once per sample. Here it *simulates* a stochastic service (true success rate ≈ 0.9) so the example runs offline; in real use this is where your API/LLM call lives. Discovered and imported automatically, like pytest's `conftest.py`. |
| `fortune-teller.yaml` | **The declaration** — the service, the criteria (one with a bar, one without), the inputs. Posture-free: the verb decides what happens. Freely named, unlike its discovered `mavai-*` neighbour.                                                                                  |

```bash
pip install "baseltest[declarative]"
cd examples/simulated-service

baseltest test fortune-teller.yaml                  # verdict against the 0.8 threshold,
                                                    #   at the bar's derived minimum
baseltest measure fortune-teller.yaml --samples 200 # everything recorded, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence, not a comparison of one lucky sample. And notice what the derived minimum implies: at n = 11, only a *perfect* run clears the 0.8 bar, so this ≈0.9-rate service fails honestly much of the time. That is the operating characteristic of the smallest feasible run — give it slack with `--samples 100` and watch the same service pass dependably. The n is visible on every run precisely so this trade-off is yours to see and make.

Then run them **in order** — `measure` first, `test` second — and watch the ratchet: the bar-less `spirits-stay-polite` criterion is skipped by the first test (*requires a baseline*), but after a measure run the next test judges it **against the baseline** — no worse than measured, the artefact named on the verdict line.

## `language-model/` — a real model, two files, no Python

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its response parsed as JSON (the `transforms:` block declares the `basket` view) and judged structurally — every item named, every quantity positive, plus an input-specific expectation (eggs in the egg order). Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
baseltest test basket-builder.yaml                  # test posture: verdict (recorded in
                                                    #   _baseltest/verdicts/), no baseline
baseltest measure basket-builder.yaml --samples 200 # measure posture: characterisation
                                                    #   + baseline artefact
baseltest explore basket-builder.yaml               # explore posture: one descriptive
                                                    #   artefact per configuration
```

The contract declares `intent: smoke` with a 0.8 bar, so a first `test` runs at the small smoke default (n = 5) — quick, cheap, and honest about what five samples can and cannot show. To graduate to a production bar: raise `threshold`, remove `intent: smoke`, and let the derived minimum size the run — or size it yourself with `--samples`. A high bar's derived minimum above 100 samples is refused rather than run silently (the message names the number to type): a materially expensive run should carry its cost visibly in the command line.

### Compare two models with one explore run

The services file also carries an `explorations:` grid: the same job on a different model — GPT-4o-mini as the baseline, Claude Haiku 4.5 as the exploration entry (and a commented-out third entry for [Apertus](https://huggingface.co/swiss-ai/Apertus-70B-Instruct-2509), the fully open Swiss model served by [Public AI](https://publicai.co)). `test` and `measure` never read the grid (they run the baseline `configuration:`); `explore` runs every point, a few samples each, and writes one descriptive YAML per configuration. Step by step:

1. **Set both credentials** (each provider uses its own conventional variable):

   ```bash
   export OPENAI_API_KEY=...      # the baseline
   export ANTHROPIC_API_KEY=...   # the claude exploration entry
   ```

   Only one key? Delete the other's entry from `mavai-services.yaml` — a one-point grid explores fine; the steps below work the same.

2. **Run the exploration** (2 configurations × 5 samples each — the default; `--samples-per-config` to change it. Quick and cheap by design: an exploration renders no verdict, so no sample count is ever "too small"):

   ```bash
   baseltest explore basket-builder.yaml
   ```

3. **Read the summary** — one line per configuration, observed rates only — then list the artefacts it wrote:

   ```bash
   ls _baseltest/explorations/basket-builder-returns-valid-baskets/
   # provider-anthropic_model-claude-haiku-4-5-20251001.yaml
   # provider-openai_model-gpt-4o-mini.yaml
   ```

4. **Diff the two models** — the files are built for exactly this: the lines that differ are the factor values and the statistics, nothing else:

   ```bash
   cd _baseltest/explorations/basket-builder-returns-valid-baskets
   diff provider-openai_model-gpt-4o-mini.yaml \
        provider-anthropic_model-claude-haiku-4-5-20251001.yaml
   ```

   Each file carries the configuration's factors, observed pass rate, per-criterion counts, and failure reasons — descriptive statistics only, triage rather than judgement.

5. **Promote the winner.** Fold its values into the `configuration:` block, then `baseltest measure` and `baseltest test` as usual. An old baseline measured under the previous configuration no longer matches — the next test names the drift and refuses to judge against stale evidence until you re-measure.

Want a third model in the comparison? Uncomment the apertus entry and `export PUBLICAI_API_KEY=...`. Apertus's hosted endpoint has no structured-output support, so `explore` runs that configuration *without* the declared `response-schema:` and says so in a console note — the system prompt still states the output shape, which keeps the comparison fair.

One design note the grid makes visible: the guide's version of this service declares a `response-schema:`. Providers differ in structured-output support (openai and anthropic honour a schema; apertus's hosted endpoint does not), and an exploration handles the mix honestly: a schema-less provider in the grid is invoked *without* the schema, announced by a console note — never silently, and never by abandoning the run. Under `measure` and `test` the same situation stays a hard refusal, because there the schema is part of the measured population's identity. When you explore across providers, carry the output shape in the system prompt — as this example does — so every model gets the same instructions and the comparison stays fair.
