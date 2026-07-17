# Examples

Ready-to-run declarative authoring, from zero. Each folder holds **one contract file, named for what it tests** — the name is yours, and you keep as many contract files as you have things to test. (The `mavai-*` files beside it are the opposite: fixed, namespaced names the reader discovers automatically — `mavai-services.yaml` for service definitions, `mavai-bindings.py` for code registrations.) What a run does is the verb you invoke it with:

- `basel test <contract-file>` — a probabilistic test: the thresholded criteria are judged (a criterion without a bar is skipped, with a notice). Produces a verdict, written as a verdict record into `_baseltest/verdicts/`; no baseline is persisted.
- `basel measure <contract-file> --samples N` — a measure experiment: **every** criterion is recorded (thresholded ones are judged too), and a baseline artefact is persisted into `_baseltest/baselines/` — the durable record of what was observed. The sample count is required: a measurement's budget is an experimental-design decision (1000 is a solid baseline-grade count; smaller deliberate budgets are legitimate).
- `basel explore <contract-file>` — an exploration: every configuration in the service's grid (the baseline plus its `explorations:` entries) runs a few samples (5 by default; `--samples-per-config` to size it), and each writes one descriptive artefact into `_baseltest/explorations/` — no verdicts, just the numbers to diff. Requires a service declared in the services file.
- `basel check <contract-file>` — the authoring loop's compile step: validates the contract against its services file and bindings (every load-time join, including each exploration grid point and every input against the binding's signature) without running a single sample. Exit 0 with one `ok:` line per validated fact; exit 2 with the same refusal a run would give.
- `basel report test` — an HTML test report from the persisted verdict records, rendered post-hoc into `_baseltest/reports/` — no service is invoked. Or render inline as part of a run with `--html-report <path>` on `test`; either way it is the same renderer, so the outputs are identical. Exploration comparison reports are rendered by the family's [mavai](https://github.com/mavai-org/mavai/releases) tool: `mavai explore _baseltest/explorations -o report.html`.

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

basel test fortune-teller.yaml                  # verdict against the 0.8 threshold,
                                                    #   at the bar's derived minimum
basel measure fortune-teller.yaml --samples 200 # everything recorded, baseline persisted
```

Run the test a few times: the observed rate moves, the verdict logic doesn't — it is a claim about the true rate at 95% confidence. At n = 11 only a *perfect* run clears the 0.8 bar, so this ≈0.9-rate service fails honestly much of the time: the derived minimum is the weakest design the bar admits, shown on every run so the trade-off is yours. `--samples 100` gives it slack by hand; the empirical criterion below gets a size computed from your stated tolerance.

Then run them **in order** — `measure` first, `test` second — and watch the ratchet: the bar-less `spirits-stay-polite` criterion is skipped by the first test (*requires a baseline*), but after a measure run the next test judges it **against the baseline** — no worse than measured, the artefact named on the verdict line. With a baseline in play the test also stops guessing its size: `basel test fortune-teller.yaml --tolerate 84` (or `tolerate: 0.84` in the file, or answer the questions it asks on a terminal) computes the smallest n at which a genuine drop to 84% fails the test about four times out of five, explained in plain language. An explicit `--samples` still works on its own, but the run states what it buys and asks before running a weak design.

Every test run you just made persisted a verdict record, so a shareable report is one command away — no re-execution:

```bash
basel report test                       # renders _baseltest/reports/test.html
open _baseltest/reports/test.html       # macOS; xdg-open on Linux
```

One self-contained page — summary stats, a colour-coded verdict table, per-criterion drill-down — that opens offline from anywhere: attach it to a PR or archive it with the build. (Prefer it in one step? `basel test fortune-teller.yaml --samples 100 --html-report report.html` renders the identical page as part of the run.)

## `rule-driven-service/` — factors and covariates: configuration citizenship for your own service

A binding's name says *which* service; it cannot say which version of the world the service ran under. The triage assistant routes support requests using the keyword rules in `triage-rules.txt`, under a configuration declared in `mavai-services.yaml` — and its identity has **two feeds** flowing into one drift-checked provenance surface:

**Computed covariates** — values YAML cannot state, declared on the registration and resolved fresh every run (the bindings file is imported on every invocation):

```python
@binding_factory(
    "triage",                                  # the service *type*
    covariates={
        "triage-rules": _RULES_FINGERPRINT,    # sha256 of triage-rules.txt
        "assistant-version": "2.0",
    },
)
def triage(tone: str = "matter-of-fact", certainty: float = 0.9) -> Callable[[str], str]:
    ...                                        # returns the per-sample callable
```

**Declared, sweepable configuration** — the factory's signature *is* the schema (kebab-case YAML keys map to snake_case parameters, defaults are the optional keys, annotations are checked), and `mavai-services.yaml` configures the named service and its exploration grid:

```yaml
services:
  triage-assistant:
    type: triage
    configuration: {tone: matter-of-fact, certainty: 0.9}
    explorations:
      - certainty: 0.7          # a markedly less certain assistant
      - tone: reassuring        # same certainty, warmer closing
```

Run the full loop (offline, like the simulated service):

```bash
cd examples/rule-driven-service
basel check request-triage.yaml                   # every join, zero samples
basel measure request-triage.yaml --samples 200   # pins the identity (both feeds)
basel test request-triage.yaml --tolerate 84      # judged against the baseline

basel explore request-triage.yaml                 # the whole grid, descriptively
ls _baseltest/explorations/triage-assistant-routes-requests/
# tone-matter-of-fact_certainty-0.9.yaml   <- the baseline
# tone-matter-of-fact_certainty-0.7.yaml   <- visibly lower observed rate
# tone-reassuring_certainty-0.9.yaml
```

`explore` runs every grid point through the factory and writes one descriptive artefact per configuration, named by its factors — diff two of them and the lines that differ are the factor values and the statistics. `test` and `measure` never read the grid: they run the baseline `configuration:`, whose keys join the covariates in the drift-checked identity. So both feeds refuse the same way:

```bash
echo "complaints: unhappy, disappointed" >> triage-rules.txt   # the rules drift
basel test request-triage.yaml --tolerate 84
# no matching baseline to size against (baseline ... was measured under a
# different configuration (differing: triage-rules)) — run `basel measure` first
```

The refusal is the feature: without the declared identity, the edited rules (or a tweaked `certainty:`) would be judged silently against evidence measured under the old ones. Re-measure to accept the new identity, or restore the file to keep the old one. A misfit between the services file and the factory's signature — an unknown key, a missing required one, a wrongly typed value — is refused at load time with the signature in the message; `basel check` runs all of those joins (and the inputs-against-signature join) without a single sample, so it belongs in your editor loop and CI. Keys the framework writes into provenance itself (`binding`, `runMode`, `serviceType`, `taskFile`, `taskFormat`) are reserved — declaring one is refused, with a pointer.

## `language-model/` — a real model, judged as structure

The basket-builder from the [getting-started guide](../docs/GETTING-STARTED.md): a language model given a job, its response parsed as JSON (the `transforms:` block declares the `basket` view) and judged structurally — every item named, every quantity positive, plus per-input expectations encoding the shop's **house conventions** (canonical names, "a dozen" means 12, weights are not quantities, …) that drive the optimize walkthrough below. A second view, `judged`, comes from a custom `@transform` in `mavai-bindings.py` — a tiny in-process judge returning a dict of derived facts — and the contract addresses it with the same `$`-rooted `path:` syntax as the stock `basket` view: any view holding structure is structurally addressable. Needs a credential for the declared provider (or edit `mavai-services.yaml` to use `anthropic`, `mistral`, `ollama`, or `apertus`):

```bash
export OPENAI_API_KEY=...
cd examples/language-model
basel test basket-builder.yaml                  # test posture: verdict (recorded in
                                                    #   _baseltest/verdicts/), no baseline
basel measure basket-builder.yaml --samples 200 # measure posture: characterisation
                                                    #   + baseline artefact
basel explore basket-builder.yaml               # explore posture: one descriptive
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
   basel explore basket-builder.yaml
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

   Each file carries the configuration's factors, observed pass rate, per-criterion counts and failure reasons, a gated latency summary (p50 at exploration-sized runs), and a per-sample **result projection** — which input drove each sample, which postconditions passed, how long the call took, and the model's response verbatim. Descriptive statistics only, triage rather than judgement — and when a configuration underperforms, the projection shows you *what it actually said*.

5. **Render the comparison report** — the diff's visual sibling, one page over every configuration, rendered by the family's shared [mavai](https://github.com/mavai-org/mavai/releases) tool:

   ```bash
   cd ../..                                # back to examples/language-model
   mavai explore _baseltest/explorations -o comparison.html
   ```

   A ranked leaderboard, a per-criterion matrix, and a latency profile per model. Like the artefacts it renders from, it is descriptive only — and because every framework in the family emits the same `mavai-explore-1` artefact schema, the same tool renders a punit or feotest exploration identically.

6. **Promote the winner.** Fold its values into the `configuration:` block, then `basel measure` and `basel test` as usual. An old baseline measured under the previous configuration no longer matches — the next test names the drift and refuses to judge against stale evidence until you re-measure.

### Watch a meta-LLM engineer the prompt

The services file's `optimizations:` section declares three searches; the `prompt-tuning` entry is the showpiece — a meta-LLM (`stepper: prompt-engineer`) reads each iteration's failures and proposes the next system prompt:

```bash
basel optimize basket-builder.yaml prompt-tuning --samples-per-iteration 30
```

A representative run (yours will differ — every number here is a stochastic observation, which is the point of the framework):

```
iteration 0: score 0.1000 (3 of 30 responses met expectations)
iteration 1: score 0.4667 (14 of 30 responses met expectations)
iteration 2: score 0.8000 (24 of 30 responses met expectations)
iteration 3: score 1.0000 (30 of 30 responses met expectations)  ← best
iteration 4: score 0.9667 (29 of 30 responses met expectations)
iteration 5: score 0.9000 (27 of 30 responses met expectations)
stopped: no improvement within the window
```

The staircase is engineered, and the machinery is worth reading because every part of it is an authoring surface you also have:

- **The contract encodes house conventions** the baseline two-line prompt does not state — names are lowercase and singular, "a dozen" becomes 12, `500g of butter` is *one* butter, an uncounted item means quantity 1, nothing is invented. A bare model cannot guess a shop's private rulebook, so iteration 0 scores honestly low.
- **Failure reasons carry the lesson.** Each per-input expectation is ordered so the first failing check produces a diagnosable reason (`response does not equal 'egg'` — a trial's reason is the *first* failing check's), and the meta-LLM must infer the general convention from the canonical value it quotes.
- **`max-exemplars: 1` meters the curriculum.** Exemplars surface in input order and the inputs are grouped by rule, so the prompt engineer sees roughly one rule class per iteration instead of the whole rulebook at once — a staircase rather than a single jump.
- **The meta prompt is itself engineered** (`stepper-config: system-prompt:`): it tells the meta-LLM to infer the convention behind the exemplar shown, add one rule with one worked example, and change nothing else. Prompt-engineering the prompt engineer is not a cheat; it is the skill the example teaches.
- **The plateau window ends the story.** Once the score stops improving (`no-improvement-window: 2`), the run stops — with the curriculum exhausted there is nothing left to learn, and the trailing wobble (a perfect prompt "improved" into a slightly worse one) is the honest reason to stop touching a winning prompt.

The artefact in `_baseltest/optimizations/` carries the full history — every prompt tried, per-iteration failure distributions, per-sample projections. Promotion is the same move as explore's: fold the winning `system-prompt` into the `configuration:` block, `basel measure`, and the drift check keeps the new identity honest.

Want a third model in the comparison? Uncomment the apertus entry and `export PUBLICAI_API_KEY=...`. Apertus's hosted endpoint has no structured-output support, so `explore` runs that configuration *without* the declared `response-schema:` and says so in a console note — the system prompt still states the output shape, which keeps the comparison fair.

One design note the grid makes visible: the guide's version of this service declares a `response-schema:`. Providers differ in structured-output support (openai and anthropic honour a schema; apertus's hosted endpoint does not), and an exploration handles the mix honestly: a schema-less provider in the grid is invoked *without* the schema, announced by a console note — never silently, and never by abandoning the run. Under `measure` and `test` the same situation stays a hard refusal, because there the schema is part of the measured population's identity. When you explore across providers, carry the output shape in the system prompt — as this example does — so every model gets the same instructions and the comparison stays fair.
