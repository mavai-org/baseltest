# baseltest

Statistically honest testing for stochastic services, in Python.

Services built on LLMs, ML models, or randomised algorithms do not pass or fail a single invocation — they succeed at a rate. baseltest treats that rate as the thing under test: run the service repeatedly, judge each response against declared criteria, and render a verdict backed by real statistics (Wilson confidence bounds, feasibility-checked sample sizes) rather than a green tick over a lucky sample.

baseltest is the Python member of the [mavai](https://mavai.org) framework family, alongside [punit](https://github.com/mavai-org/punit) (Java) and [feotest](https://github.com/mavai-org/feotest) (Rust). It shares their statistical methodology — every formula is validated against the family's [statistical oracle](https://github.com/mavai-org/mavai-R) — and expresses it in Python idioms rather than porting either framework.

## Where the project stands

The **statistics core** (`baseltest.statistics`) is implemented and conformance-validated against the oracle's published reference cases: Wilson score construction, threshold derivation, feasibility checking, and sampling-power arithmetic, built on scipy/statsmodels.

The framework around it is in active development.

## Try it in two minutes

The repository ships a ready-to-run example that needs no API key, no network, and no Python of your own — the service under test is simulated:

baseltest requires **Python 3.11 or newer**. Check what you have first:

```bash
python3 --version
```

If that prints 3.11+ you can use `python3` below. Otherwise install a newer interpreter — it will live alongside your system Python, nothing is replaced:

- **macOS (Homebrew):** `brew install python@3.12` → the interpreter is `python3.12`. If the command isn't found afterwards, run `brew link python@3.12` or use the full path `$(brew --prefix python@3.12)/bin/python3.12`.
- **Linux (Debian/Ubuntu):** `sudo apt install python3.12 python3.12-venv` (on older releases, via the deadsnakes PPA).
- **Any platform, [pyenv](https://github.com/pyenv/pyenv):** `pyenv install 3.12 && pyenv local 3.12`.
- **Any platform, [uv](https://docs.astral.sh/uv/):** `uv venv --python 3.12` creates the venv below in one step.

Then — creating the venv **with the new interpreter** is the step that matters; installing 3.12 alone changes nothing until a venv is built from it:

```bash
git clone https://github.com/mavai-org/baseltest.git
cd baseltest

python3.12 -m venv venv          # or python3, if yours is already 3.11+
source venv/bin/activate
python --version                 # verify: must print 3.11+ — if not, stop and re-check the venv line
pip install -e ".[declarative]"   # the baseltest package ships the `basel` command

cd examples/simulated-service
basel test fortune-teller.yaml      # judge it against its declared bar
basel measure fortune-teller.yaml --samples 200   # or: record everything, persist a baseline
```

(If pip ever answers with `Package 'baseltest' requires a different Python`, that is this issue: the active `pip` still belongs to an older interpreter. `deactivate`, delete `venv/`, and recreate it with the 3.11+ interpreter as above.)

You'll see a verdict with its uncertainty stated — run the test a few times and watch the observed rate move while the conclusion stays statistically honest. The `measure` verb is the other posture over the same file: every criterion recorded, a baseline artefact persisted. A third verb, `explore`, sweeps a grid of service configurations declared in the services file and writes one descriptive artefact per configuration — triage before you measure. A fourth, `optimize`, searches the configuration space iteratively — a declared stepper proposes each next configuration, a scorer judges each iteration, and the full history is persisted as one artefact. Everything a run generates lands under `_baseltest/` in the working directory. When you have a model credential to hand, `examples/language-model/` runs a real language-model service from two small files — its grid pits two models against each other (GPT-4o-mini and Claude Haiku 4.5, with an optional entry for the fully open Swiss Apertus), so one `basel explore` run and one `diff` compare them on the same job; the [examples README](examples/README.md) has the step-by-step, and the [getting-started guide](docs/GETTING-STARTED.md) walks through all the verbs.

## The command line

The `baseltest` package ships one command, `basel`, with six run and reporting verbs. The contract file carries the claim; the verb carries the posture; the invocation carries the budget.

| Verb | What it does | Sizing |
|---|---|---|
| `basel check <contract.yaml>` | Validates the contract against its services file, bindings, and `path:` expressions — every load-time join, **zero samples**: the authoring loop's compile step. | No sampling. |
| `basel test <contract.yaml>` | Judges the thresholded criteria (and any declared latency bounds): a statistical verdict with its uncertainty stated, persisted as a verdict record. | Empirical criteria are sized from your stated risk: `--tolerate` (or the criterion's `tolerate:` key) and `--confidence` compute the required n, prompted for on a terminal when unclaimed. Declared bars default to their feasibility minimum (a silently derived n above 100 is refused); `--samples N` sizes it yourself — explained, and confirmed when weak (`--accept-weak-design` for automation). |
| `basel measure <contract.yaml> --samples N` | Records **every** criterion and persists the baseline artefact — the durable record future empirical bars derive from, latency profile included. | `--samples` is required: a measurement's budget is an experimental-design decision. |
| `basel explore <contract.yaml>` | Runs every configuration in the service's grid and writes one descriptive artefact per configuration — triage, no verdicts. | `--samples-per-config` (default 5; no count is ever refused as too small). |
| `basel optimize <contract.yaml> [id]` | Runs one declared optimization: an iterative configuration search driven by its stepper, scored per iteration, the full history persisted as one artefact — descriptive, no verdicts. With several entries declared the id is required (or `--all`); never guessed. | `--samples-per-iteration` (default 20). |
| `basel report test` | Renders a self-contained HTML report from persisted verdict records — post-hoc, never invokes a service. `report measure` is reserved. Exploration comparison reports are rendered by the family's [mavai](https://github.com/mavai-org/mavai/releases) tool: `mavai explore <dir> [-o report.html]`. | `--out` to relocate (default `_baseltest/reports/`). |

Frequently reached-for flags: `--html-report <path>` on `test` renders the report inline as part of the run (the same renderer as `basel report test`, so the two outputs are identical); `--baseline-dir`, `--verdict-dir`, `--explorations-dir`, and `--optimizations-dir` relocate the artefact directories. Everything a run generates lands under `_baseltest/`.

Exit codes are contractual, made for CI: `0` success · `1` judgement failure (a declared bar or latency bound was breached) · `2` refusal (the service was never invoked: malformed file, unsupportable configuration, nothing to render) · `3` unsupportable (the evidence cannot carry the assertion in either direction). The [getting-started guide](docs/GETTING-STARTED.md) walks through all of it, and the [user guide](docs/USER-GUIDE.md) is the complete reference — every verb, every file, every option.

## The declarative core

baseltest is **declarative-first**. The primary way to author a test is a small, language-agnostic contract file — inputs, expectations, a service binding, a threshold — which baseltest turns into a full service contract evaluated by the statistical machinery. No statistical vocabulary is required to get a first honest result:

```yaml
format: mavai-contract/1
contract: greeting-service-is-polite
service: greeting-service
inputs:
  - "Alice"
  - "Bob"
criteria:
  - threshold: 0.95
    contains: "hello"
```

What that core gives you today:

- **Honest output**: a declared threshold yields a statistical verdict with its uncertainty stated; no threshold yields a measurement explicitly labelled as an observation, never dressed up as a pass.
- **Multiple criteria per contract**: a service examined through several Bernoulli streams in one run — relevance at one bar, well-formedness at another.
- **Structured-response checks**: JSON, XML, and YAML transforms with standards-pinned path expressions (RFC 9535 JSONPath, XPath 1.0) — and the same `path:` expressions address the structured value of any transform you register in code.
- **Measurement runs** that persist a baseline artefact — the empirical record future regression tests verify against.

On the roadmap:

- **An lm-eval bridge** (separate package): mavai-grade statistics over [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) runs, with baseltest as the statistical engine underneath.

## Status

Pre-release (`0.3.0.dev0`). APIs and the contract-file surface are settling; nothing here is stable yet. If the approach interests you, [mavai.org](https://mavai.org) explains the methodology, and punit's user guide shows the mature end of the same ideas.

## Licence

See [LICENSE](LICENSE).
