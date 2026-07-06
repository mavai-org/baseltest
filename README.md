# baseltest

Statistically honest testing for stochastic services, in Python.

Services built on LLMs, ML models, or randomised algorithms do not pass or fail a single invocation — they succeed at a rate. baseltest treats that rate as the thing under test: run the service repeatedly, judge each response against declared criteria, and render a verdict backed by real statistics (Wilson confidence bounds, feasibility-checked sample sizes) rather than a green tick over a lucky sample.

baseltest is the Python member of the [mavai](https://mavai.org) framework family, alongside [punit](https://github.com/mavai-org/punit) (Java) and [feotest](https://github.com/mavai-org/feotest) (Rust). It shares their statistical methodology — every formula is validated against the family's [statistical oracle](https://github.com/mavai-org/mavai-R) — and expresses it in Python idioms rather than porting either framework.

## Where the project stands

The **statistics core** (`baseltest.statistics`) is implemented and conformance-validated against the oracle's published reference cases: Wilson score construction, threshold derivation, feasibility checking, and sampling-power arithmetic, built on scipy/statsmodels.

The framework around it is in active development.

## Where the project is going

baseltest is being built **declarative-first**. The primary way to author a test will be a small, language-agnostic task file — inputs, expectations, a service binding, a threshold, a sample count — which baseltest turns into a full service contract evaluated by the statistical machinery. No statistical vocabulary is required to get a first honest result:

```yaml
format: mavai-task/1
task: greeting-service-is-polite
service: greeting-service
samples: 100
inputs:
  - "Alice"
  - "Bob"
criteria:
  - threshold: 0.95
    contains: "hello"
```

Planned around that core:

- **Honest output**: a declared threshold yields a statistical verdict with its uncertainty stated; no threshold yields a measurement explicitly labelled as an observation, never dressed up as a pass.
- **Multiple criteria per task**: a service examined through several Bernoulli streams in one run — relevance at one bar, well-formedness at another.
- **Structured-response checks**: JSON, XML, and YAML transforms with standards-pinned path expressions (RFC 9535 JSONPath, XPath 1.0).
- **Measurement runs** that persist a baseline artefact — the empirical record future regression tests will verify against.
- **A graduation path**: when the task file runs out of expressive power, baseltest emits the equivalent contract as Python source you take ownership of — the same object you were already running, not a migration.
- **An lm-eval bridge** (separate package): mavai-grade statistics over [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) runs, with baseltest as the statistical engine underneath.

## Status

Pre-release (`0.1.0.dev0`). APIs and the task-file surface are settling; nothing here is stable yet. If the approach interests you, [mavai.org](https://mavai.org) explains the methodology, and punit's user guide shows the mature end of the same ideas.

## Licence

See [LICENSE](LICENSE).
