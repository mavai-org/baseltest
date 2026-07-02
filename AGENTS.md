# AGENTS.md

Guidance for coding agents (and human contributors) working in this repository.

## Project overview

`baseltest` is a Python-native framework for probabilistic testing of
stochastic services (LLMs, ML models, randomized algorithms, network-dependent
services). It is the Python member of the mavai framework family, alongside
`punit` (Java) and `feotest` (Rust): same statistical methodology, idiomatic
per-language implementation, not a port.

The project is early-stage: only packaging and tooling scaffolding exists so
far. Internal architecture (module layout beyond the package root, statistical
approach, API shape) is not yet decided and should not be assumed from
`punit` or `feotest` — it will be worked out via orchestrator directives as
implementation begins.

## Environment setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11+ is required (see `pyproject.toml`).

## Build, test, and quality commands

```bash
# Run the test suite
pytest

# Run a single test file
pytest tests/test_something.py

# Run a single test by name (substring match)
pytest -k test_name

# Run with coverage report (also the default via pyproject addopts)
pytest --cov=baseltest --cov-report=term-missing

# Lint
ruff check .

# Format
ruff format .

# Format check (CI-friendly, no rewrite)
ruff format --check .

# Static type check
mypy src

# Build distributable artifacts
python -m build
```

Run `ruff check .`, `ruff format --check .`, `mypy src`, and `pytest` before
opening a pull request — the same set CI enforces.

## Current layout

```
src/baseltest/   # package root — __init__.py + py.typed only, so far
tests/           # conftest.py only, so far
```

Do not pre-create subpackages or modules ahead of an actual directive to
implement something — the internal architecture (module layout, statistical
approach, API shape, exception vs. result-object conventions for expected
failures) is an open design question, not settled by this scaffold.

## Conventions

- Target Python 3.11+; use modern typing (`X | Y` unions, `list[str]`, no
  `from __future__ import annotations` needed).
- Every public function and class carries type hints; `mypy --strict` must
  pass.
- Every public module, class, and function carries a docstring
  (Google or NumPy style — pick one and stay consistent within a module).
- Formatting and linting are enforced by `ruff` (see `[tool.ruff]` in
  `pyproject.toml`), not by hand; do not hand-format around `ruff format`'s
  output.
- Observe a consistent level of abstraction in any given unit of
  functionality: a public method expressing high-level business logic should
  not contain low-level detail (string parsing, file I/O) inline — delegate
  to a helper that is tested in its own right. Small, trivial exceptions are
  fine where the extra abstraction would not pay for itself.
- All non-trivial functionality is covered by unit tests; functionality
  dependent on resources outside the test's control gets an integration test
  instead, kept separately identifiable (e.g. `@pytest.mark.integration`).
- Construct test assertions as plain `assert` statements (pytest's assertion
  rewriting gives readable failure output without a separate assertion
  library).

## Requirement-code isolation

Internal feature-tracking codes used in orchestrator planning documents
(short letter-prefix codes such as `PT13`, `EX06`, `RP01`) must never appear
in this repository's source — production or test. A reader of this
open-source code has no context for them. Refer to features by their domain
name ("baseline integrity check", "passing-only latency block") instead.

## License and contributions

Apache License 2.0 (see `LICENSE`). Contributions require a `Signed-off-by`
line per the Developer Certificate of Origin — see `CONTRIBUTING.md` and
`dco.txt`.
