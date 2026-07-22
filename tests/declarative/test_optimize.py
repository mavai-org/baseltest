"""The optimize verb: entry validation, selection, the loop, and the built-in steppers."""

import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from baseltest.declarative import Registry, optimize
from baseltest.declarative._cli import main
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import ENV_ENDPOINT, ENV_MODEL
from baseltest.declarative._runner import check
from baseltest.declarative._services import parse_services

CONTRACT = """
format: mavai-contract/1
contract: support-agent-tuning
service: support-agent
inputs: ["Where is my order?", "Do you ship abroad?"]
criteria:
  - name: says-hello
    contains: "hello"
"""


def services_yaml(optimizations: str) -> str:
    return f"""
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
      temperature: 0.2
    optimizations:
{optimizations}
"""


LINEAR_ENTRY = """
      - id: temperature-linear
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        initial: {temperature: 0.0}
        max-iterations: 11
"""

TWO_ENTRIES = """
      - id: temperature-linear
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        initial: {temperature: 0.0}
        max-iterations: 11
      - id: temperature-honing
        stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.5, min-step: 0.25}
        initial: {temperature: 0.0}
        max-iterations: 20
"""


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


@pytest.fixture()
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, Any]]]:
    """A stubbed OpenAI-compatible endpoint whose replies a test scripts.

    The test passes ``respond(payload) -> content``; every captured request
    payload is returned for assertion.
    """

    def install(respond: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []

        def fake_urlopen(request: Any) -> FakeResponse:
            payload = json.loads(request.data.decode("utf-8"))
            captured.append(payload)
            reply = {"choices": [{"message": {"content": respond(payload)}}]}
            return FakeResponse(json.dumps(reply).encode("utf-8"))

        monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/v1/chat/completions")
        monkeypatch.setenv(ENV_MODEL, "env-default-model")
        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        return captured

    return install


def hello_below(cutoff: float) -> Callable[[dict[str, Any]], str]:
    """Pass (say hello) iff the request's temperature is at or below the cutoff."""

    def respond(payload: dict[str, Any]) -> str:
        return "hello there" if payload.get("temperature", 1.0) <= cutoff else "goodbye"

    return respond


def write_files(tmp_path: Path, services: str, contract: str = CONTRACT) -> Path:
    (tmp_path / "mavai-services.yaml").write_text(services, encoding="utf-8")
    path = tmp_path / "contract.yaml"
    path.write_text(contract, encoding="utf-8")
    return path


def refused(services: str) -> str:
    with pytest.raises(ContractConfigurationError) as caught:
        parse_services(services, Registry())
    return str(caught.value)


class TestEntryValidation:
    def test_unknown_entry_key_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - id: x
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        disable-early-termination: true
"""
            )
        )
        assert "unknown key `disable-early-termination:`" in message

    def test_id_is_required_with_several_entries(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
      - stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.5, min-step: 0.25}
        max-iterations: 3
"""
            )
        )
        assert "`id:` is required" in message

    def test_a_lone_entry_defaults_its_id_to_the_service_name(self) -> None:
        definitions = parse_services(
            services_yaml(LINEAR_ENTRY.replace("id: temperature-linear\n        ", "")),
            Registry(),
        )
        (entry,) = definitions["support-agent"].optimizations
        assert entry.run_id == "support-agent"

    def test_duplicate_ids_are_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - id: twin
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
      - id: twin
        stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.5, min-step: 0.25}
        max-iterations: 3
"""
            )
        )
        assert "`id: twin` is already used" in message

    def test_an_id_that_cannot_name_a_file_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - id: "one/two"
        stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
"""
            )
        )
        assert "letters, digits, dots, underscores, or hyphens" in message

    def test_an_unknown_stepper_is_refused_with_the_registered_names(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweeep
        max-iterations: 3
"""
            )
        )
        assert "unknown `stepper: linear-sweeep`" in message
        assert "linear-sweep" in message
        assert "did you mean" in message

    def test_an_unknown_scorer_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        scorer: pass-rat
        max-iterations: 3
"""
            )
        )
        assert "unknown `scorer: pass-rat`" in message
        assert "pass-rate" in message

    def test_an_objective_outside_the_vocabulary_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        objective: bigger
        max-iterations: 3
"""
            )
        )
        assert "`objective:` must be one of maximize, minimize" in message

    def test_max_iterations_is_required(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
"""
            )
        )
        assert "`max-iterations:` is required" in message

    def test_a_non_positive_window_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        no-improvement-window: 0
"""
            )
        )
        assert "`no-improvement-window:` must be a positive integer" in message

    def test_stepper_config_that_does_not_fit_the_factory_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5, wobble: 3}
        max-iterations: 3
"""
            )
        )
        assert "unknown key `wobble:`" in message
        assert "linear-sweep(" in message  # the signature travels in the refusal

    def test_stepper_config_missing_a_required_parameter_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1}
        max-iterations: 3
"""
            )
        )
        assert "missing `stop:`" in message

    def test_stepper_config_with_a_mistyped_value_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: warm, stop: 0.5}
        max-iterations: 3
"""
            )
        )
        assert "`step:` expects float" in message

    def test_a_stepper_targeting_an_undeclared_configuration_key_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: top-p, step: 0.1, stop: 0.5}
        max-iterations: 3
"""
            )
        )
        assert "targets configuration key 'top-p'" in message
        assert "available keys" in message

    def test_an_initial_overlay_restating_the_baseline_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        initial: {temperature: 0.2}
"""
            )
        )
        assert "merely restates" in message

    def test_an_initial_key_without_a_value_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        initial: {temperature: }
"""
            )
        )
        assert "declares no value" in message

    def test_an_initial_key_the_type_does_not_accept_is_refused(self) -> None:
        message = refused(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        initial: {warmth: 0.0}
"""
            )
        )
        assert "unknown key `warmth:`" in message

    def test_an_inert_plateau_window_is_noted_not_refused(self) -> None:
        definitions = parse_services(
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 3
        no-improvement-window: 3
"""
            ),
            Registry(),
        )
        (entry,) = definitions["support-agent"].optimizations
        assert any("plateau detection is inert" in note for note in entry.notes)

    def test_a_user_stepper_registered_with_the_decorator_resolves(self) -> None:
        registry = Registry()

        @registry.stepper("hold-still")
        def hold_still():  # type: ignore[no-untyped-def]
            return lambda current, ctx: None

        definitions = parse_services(
            services_yaml(
                """
      - stepper: hold-still
        max-iterations: 3
"""
            ),
            registry,
        )
        (entry,) = definitions["support-agent"].optimizations
        assert entry.stepper_name == "hold-still"

    def test_a_builtin_stepper_name_cannot_be_shadowed(self) -> None:
        registry = Registry()
        with pytest.raises(ContractConfigurationError, match="built-in stepper"):

            @registry.stepper("refining-grid")
            def usurper():  # type: ignore[no-untyped-def]
                return lambda current, ctx: None

    def test_a_builtin_scorer_name_cannot_be_shadowed(self) -> None:
        registry = Registry()
        with pytest.raises(ContractConfigurationError, match="built-in scorer"):

            @registry.scorer("pass-rate")
            def usurper(summary):  # type: ignore[no-untyped-def]
                return 0.0


class TestSelection:
    def test_a_sole_entry_runs_without_an_id(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.0))
        path = write_files(tmp_path, services_yaml(LINEAR_ENTRY))
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        assert [o.run_id for o in outcomes] == ["temperature-linear"]

    def test_several_entries_without_an_id_are_refused_with_the_ids(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.0))
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        with pytest.raises(ContractConfigurationError) as caught:
            optimize(path, emit=False, optimizations_dir=tmp_path / "o")
        message = str(caught.value)
        assert "temperature-linear, temperature-honing" in message
        assert "--all" in message

    def test_an_unknown_id_is_refused_with_the_declared_ids(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.0))
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        with pytest.raises(ContractConfigurationError) as caught:
            optimize(path, run_id="temperature-cubed", emit=False, optimizations_dir=tmp_path / "o")
        assert "no optimization with id 'temperature-cubed'" in str(caught.value)

    def test_all_entries_runs_every_declared_entry(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.0))
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        outcomes = optimize(
            path,
            all_entries=True,
            samples_per_iteration=2,
            emit=False,
            optimizations_dir=tmp_path / "o",
        )
        assert [o.run_id for o in outcomes] == ["temperature-linear", "temperature-honing"]
        assert all(o.path.is_file() for o in outcomes)

    def test_a_service_without_an_optimizations_section_is_refused(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.0))
        services = """
format: mavai-services/1
services:
  support-agent:
    type: language-model
    configuration:
      system-prompt: "You are a support agent."
      model: small-model
"""
        path = write_files(tmp_path, services)
        with pytest.raises(ContractConfigurationError, match="declares no `optimizations:`"):
            optimize(path, emit=False, optimizations_dir=tmp_path / "o")


class TestOptimizeLoop:
    def test_iteration_zero_is_the_baseline_with_the_initial_overlay(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        captured = scripted_endpoint(hello_below(1.0))
        path = write_files(tmp_path, services_yaml(LINEAR_ENTRY))
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        assert dict(record.iterations[0].factors)["temperature"] == 0.0
        assert captured[0]["temperature"] == 0.0

    def test_no_initial_overlay_starts_from_the_baseline(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        registry = Registry()

        @registry.stepper("hold-still")
        def hold_still():  # type: ignore[no-untyped-def]
            return lambda current, ctx: None

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: hold-still
        max-iterations: 3
"""
            ),
        )
        outcomes = optimize(
            path,
            samples_per_iteration=2,
            emit=False,
            optimizations_dir=tmp_path / "o",
            registry=registry,
        )
        record = outcomes[0].record
        assert dict(record.iterations[0].factors)["temperature"] == 0.2
        assert record.termination == "stepper-stopped"
        assert len(record.iterations) == 1

    def test_the_plateau_window_stops_a_run_that_stops_improving(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(-1.0))  # nothing ever passes; scores never improve
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 5.0}
        initial: {temperature: 0.0}
        max-iterations: 11
        no-improvement-window: 2
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        assert record.termination == "no-improvement-window"
        # Iteration 0 sets the best; two further non-improving iterations fill the window.
        assert len(record.iterations) == 3

    def test_the_iteration_cap_stops_a_run_the_stepper_would_continue(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 5.0}
        initial: {temperature: 0.0}
        max-iterations: 3
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        assert record.termination == "max-iterations"
        assert len(record.iterations) == 3

    def test_re_measuring_a_configuration_is_legitimate_and_noted(
        self,
        tmp_path: Path,
        scripted_endpoint: Callable[..., list[dict[str, Any]]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A stochastic score is noisy: revisiting a configuration pools
        evidence, so the run proceeds and says the repeat is deliberate."""
        scripted_endpoint(hello_below(1.0))
        registry = Registry()

        @registry.stepper("second-opinion")
        def second_opinion():  # type: ignore[no-untyped-def]
            def step(current, ctx):  # type: ignore[no-untyped-def]
                return dict(current) if ctx.iteration < 3 else None

            return step

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: second-opinion
        max-iterations: 5
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=2, optimizations_dir=tmp_path / "o", registry=registry
        )
        record = outcomes[0].record
        assert len(record.iterations) == 3  # the same configuration, measured thrice
        factors = [dict(capture.factors) for capture in record.iterations]
        assert factors[0] == factors[1] == factors[2]
        out = capsys.readouterr().out
        assert "re-measures a configuration this run has already visited" in out
        assert "accumulate evidence" in out

    def test_a_stepper_returning_a_non_mapping_is_refused(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        registry = Registry()

        @registry.stepper("confused")
        def confused():  # type: ignore[no-untyped-def]
            return lambda current, ctx: 0.7

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: confused
        max-iterations: 3
"""
            ),
        )
        with pytest.raises(ContractConfigurationError, match="not a configuration mapping"):
            optimize(
                path,
                samples_per_iteration=2,
                emit=False,
                optimizations_dir=tmp_path / "o",
                registry=registry,
            )

    def test_a_stepper_proposing_an_invalid_configuration_is_refused_naming_the_key(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        registry = Registry()

        @registry.stepper("vandal")
        def vandal():  # type: ignore[no-untyped-def]
            return lambda current, ctx: {**current, "warmth": 0.7}

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: vandal
        max-iterations: 3
"""
            ),
        )
        with pytest.raises(ContractConfigurationError) as caught:
            optimize(
                path,
                samples_per_iteration=2,
                emit=False,
                optimizations_dir=tmp_path / "o",
                registry=registry,
            )
        message = str(caught.value)
        assert "unknown key `warmth:`" in message
        assert "from stepper 'vandal'" in message

    def test_minimize_objective_selects_the_lowest_score(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.05))  # passes only at temperature 0.0
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.2}
        initial: {temperature: 0.0}
        objective: minimize
        max-iterations: 4
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        # Under minimize, the failing iterations (score 0.0) beat the passing one.
        assert record.best.score == 0.0
        assert dict(record.best.factors)["temperature"] > 0.0

    def test_the_context_carries_budget_visibility_and_the_best(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        seen: list[tuple[int, int, float | None]] = []
        registry = Registry()

        @registry.stepper("observer")
        def observer():  # type: ignore[no-untyped-def]
            def step(current, ctx):  # type: ignore[no-untyped-def]
                seen.append(
                    (ctx.iteration, ctx.iterations_remaining, ctx.best.score if ctx.best else None)
                )
                if ctx.iterations_remaining == 0:
                    return None
                return {**current, "temperature": current["temperature"] + 0.1}

            return step

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: observer
        initial: {temperature: 0.0}
        max-iterations: 3
"""
            ),
        )
        optimize(
            path,
            samples_per_iteration=2,
            emit=False,
            optimizations_dir=tmp_path / "o",
            registry=registry,
        )
        assert seen == [(1, 2, 1.0), (2, 1, 1.0)]

    def test_failure_exemplars_reach_the_stepper_with_input_and_reason(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(-1.0))  # every sample fails
        observed: list[Any] = []
        registry = Registry()

        @registry.stepper("post-mortem")
        def post_mortem():  # type: ignore[no-untyped-def]
            def step(current, ctx):  # type: ignore[no-untyped-def]
                observed.append(ctx.history[-1].failures_by_criterion)
                return None

            return step

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: post-mortem
        max-iterations: 3
"""
            ),
        )
        optimize(
            path,
            samples_per_iteration=2,
            emit=False,
            optimizations_dir=tmp_path / "o",
            registry=registry,
        )
        detail = observed[0]["says-hello"]
        assert detail.count == 2
        assert detail.exemplars[0].input == "Where is my order?"
        assert "hello" in detail.exemplars[0].reason

    def test_a_registered_scorer_drives_best_tracking(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))  # every iteration's pass rate is 1.0
        registry = Registry()

        @registry.scorer("coolness")
        def coolness(summary):  # type: ignore[no-untyped-def]
            return float(summary.passes)  # constant across iterations, like pass-rate

        @registry.stepper("two-steps")
        def two_steps():  # type: ignore[no-untyped-def]
            def step(current, ctx):  # type: ignore[no-untyped-def]
                if ctx.iteration >= 2:
                    return None
                return {**current, "temperature": current["temperature"] + 0.1}

            return step

        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: two-steps
        scorer: coolness
        initial: {temperature: 0.0}
        max-iterations: 5
"""
            ),
        )
        outcomes = optimize(
            path,
            samples_per_iteration=2,
            emit=False,
            optimizations_dir=tmp_path / "o",
            registry=registry,
        )
        record = outcomes[0].record
        assert [capture.score for capture in record.iterations] == [2.0, 2.0]
        assert record.best_index == 0  # a tie is not an improvement


class TestBuiltinSteppers:
    def test_linear_sweep_walks_the_key_to_the_stop_bound(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        path = write_files(tmp_path, services_yaml(LINEAR_ENTRY))
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        walked = [dict(capture.factors)["temperature"] for capture in record.iterations]
        assert walked == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        assert record.termination == "stepper-stopped"

    def test_refining_grid_stops_when_no_challenger_stays_plausible(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(0.05))  # a clean peak at the low end
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: refining-grid
        stepper-config: {key: temperature, lo: 0.0, hi: 1.0, step: 0.5, min-step: 0.25}
        initial: {temperature: 0.0}
        max-iterations: 20
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=4, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        probed = [dict(capture.factors)["temperature"] for capture in record.iterations]
        # Iteration 0 (the initial overlay), then the whole coarse grid —
        # revisiting 0.0 pools its evidence rather than being skipped. The
        # losers' intervals cannot carry a meaningful advantage over a
        # pooled 8/8, so the search stops without refinement or epochs.
        assert probed == [0.0, 0.0, 0.5, 1.0]
        assert record.termination == "stepper-stopped"
        provenance = dict(record.stepper)
        assert provenance["selectedValue"] == 0.0
        assert provenance["stoppingReason"] == "no-plausible-challenger"
        assert provenance["confirmed"] is False

    def test_refining_grid_refines_confirms_and_prefers_low_on_a_tie(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        def graded(payload: dict[str, Any]) -> str:
            # One prompt tolerates heat up to 0.75, the other only to 0.4:
            # pass rates 1.0 / 0.5 / 0.0 across the grid — enough ambiguity
            # to keep a challenger alive into refinement and confirmation.
            temperature = payload.get("temperature", 1.0)
            tolerant = payload["messages"][1]["content"] == "Where is my order?"
            return "hello there" if temperature <= (0.75 if tolerant else 0.4) else "goodbye"

        scripted_endpoint(graded)
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: refining-grid
        stepper-config:
          key: temperature
          lo: 0.0
          hi: 1.0
          step: 0.5
          min-step: 0.25
          min-improvement: 0.05
          confirmation-epochs: 1
        initial: {temperature: 0.0}
        max-iterations: 20
"""
            ),
        )
        outcomes = optimize(
            path, samples_per_iteration=4, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        probed = [dict(capture.factors)["temperature"] for capture in record.iterations]
        # Coarse grid (0.0 pooled with iteration 0), refinement around the
        # leader at half the step, then one confirmation epoch of the two
        # finalists; 0.0 and 0.25 both measure perfect, so the practical
        # tie resolves to the lower temperature.
        assert probed == [0.0, 0.0, 0.5, 1.0, 0.0, 0.25, 0.5, 0.0, 0.25]
        assert record.termination == "stepper-stopped"
        provenance = dict(record.stepper)
        assert provenance["selectedValue"] == 0.0
        assert provenance["stoppingReason"] == "min-step"
        assert provenance["confirmed"] is True
        assert "0.25" in provenance["finalists"]


META_MARKER = "You are a prompt engineer"


class TestPromptEngineer:
    @pytest.fixture()
    def prompt_tuning_endpoint(
        self, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """The service passes only under an improved prompt; the meta model
        (recognised by its prompt-engineer system prompt) always proposes one."""

        def respond(payload: dict[str, Any]) -> str:
            system = payload["messages"][0]["content"]
            if META_MARKER in system:
                return "IMPROVED: respond with hello"
            return "hello there" if system.startswith("IMPROVED") else "goodbye"

        return scripted_endpoint(respond)

    def prompt_services(self) -> str:
        return services_yaml(
            """
      - id: prompt-tuning
        stepper: prompt-engineer
        stepper-config: {model: big-model, temperature: 0.9}
        max-iterations: 2
"""
        )

    def test_the_meta_message_carries_the_failure_breakdown(
        self, tmp_path: Path, prompt_tuning_endpoint: list[dict[str, Any]]
    ) -> None:
        path = write_files(tmp_path, self.prompt_services())
        optimize(path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o")
        meta_calls = [
            p for p in prompt_tuning_endpoint if META_MARKER in p["messages"][0]["content"]
        ]
        assert len(meta_calls) == 1
        message = meta_calls[0]["messages"][1]["content"]
        assert "You are a support agent." in message  # the incumbent prompt travels
        assert "Pass rate achieved: 0.00" in message
        assert 'criterion "says-hello" failed 2 time(s)' in message
        assert 'input "Where is my order?"' in message

    def test_the_suggestion_lands_in_the_target_key_and_the_run_improves(
        self, tmp_path: Path, prompt_tuning_endpoint: list[dict[str, Any]]
    ) -> None:
        path = write_files(tmp_path, self.prompt_services())
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        record = outcomes[0].record
        factors = dict(record.iterations[1].factors)
        assert factors["system-prompt"] == "IMPROVED: respond with hello"
        assert record.best_index == 1
        assert record.best.score == 1.0

    def test_the_meta_model_defaults_are_overridable_and_recorded(
        self, tmp_path: Path, prompt_tuning_endpoint: list[dict[str, Any]]
    ) -> None:
        path = write_files(tmp_path, self.prompt_services())
        outcomes = optimize(
            path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o"
        )
        meta_calls = [
            p for p in prompt_tuning_endpoint if META_MARKER in p["messages"][0]["content"]
        ]
        assert meta_calls[0]["model"] == "big-model"
        assert meta_calls[0]["temperature"] == 0.9
        provenance = dict(outcomes[0].record.stepper)
        assert provenance["name"] == "prompt-engineer"
        assert provenance["model"] == "big-model"
        assert provenance["metaModel"] == "big-model"

    def test_the_meta_model_defaults_to_the_services_own(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        def respond(payload: dict[str, Any]) -> str:
            system = payload["messages"][0]["content"]
            if META_MARKER in system:
                return "IMPROVED: respond with hello"
            return "goodbye"

        captured = scripted_endpoint(respond)
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - id: prompt-tuning
        stepper: prompt-engineer
        max-iterations: 2
"""
            ),
        )
        optimize(path, samples_per_iteration=2, emit=False, optimizations_dir=tmp_path / "o")
        meta_calls = [p for p in captured if META_MARKER in p["messages"][0]["content"]]
        assert meta_calls[0]["model"] == "small-model"  # the service's own model


class TestCheckVerb:
    def test_check_validates_the_optimizations_for_zero_samples(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        captured = scripted_endpoint(hello_below(1.0))
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        facts = check(path)
        assert any("optimizations: 2 entries validated" in fact for fact in facts)
        assert captured == []  # zero samples, zero invocations

    def test_check_surfaces_the_inert_window_note(
        self, tmp_path: Path, scripted_endpoint: Callable[..., list[dict[str, Any]]]
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        path = write_files(
            tmp_path,
            services_yaml(
                """
      - stepper: linear-sweep
        stepper-config: {key: temperature, step: 0.1, stop: 0.5}
        max-iterations: 2
        no-improvement-window: 5
"""
            ),
        )
        facts = check(path)
        assert any("plateau detection is inert" in fact for fact in facts)


class TestCli:
    def test_the_verb_runs_a_named_entry(
        self,
        tmp_path: Path,
        scripted_endpoint: Callable[..., list[dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        monkeypatch.chdir(tmp_path)
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        code = main(["optimize", str(path), "temperature-linear", "--samples-per-iteration", "2"])
        assert code == 0
        artefact = tmp_path / "_baseltest" / "optimizations" / "support-agent-tuning"
        assert (artefact / "temperature-linear.yaml").is_file()
        assert not (artefact / "temperature-honing.yaml").exists()

    def test_the_verb_refuses_an_ambiguous_selection(
        self,
        tmp_path: Path,
        scripted_endpoint: Callable[..., list[dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        monkeypatch.chdir(tmp_path)
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        code = main(["optimize", str(path)])
        assert code == 2
        stderr = capsys.readouterr().err
        assert "temperature-linear, temperature-honing" in stderr

    def test_the_verb_refuses_an_id_together_with_all(
        self,
        tmp_path: Path,
        scripted_endpoint: Callable[..., list[dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        monkeypatch.chdir(tmp_path)
        path = write_files(tmp_path, services_yaml(TWO_ENTRIES))
        code = main(["optimize", str(path), "temperature-linear", "--all"])
        assert code == 2
        assert "not both" in capsys.readouterr().err

    def test_the_summary_is_descriptive_and_names_the_artefact(
        self,
        tmp_path: Path,
        scripted_endpoint: Callable[..., list[dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        scripted_endpoint(hello_below(1.0))
        monkeypatch.chdir(tmp_path)
        path = write_files(tmp_path, services_yaml(LINEAR_ENTRY))
        code = main(["optimize", str(path), "--samples-per-iteration", "2"])
        assert code == 0
        out = capsys.readouterr().out
        assert "n = 2 per iteration" in out
        assert "renders no verdict" in out
        assert "best factors" in out
        assert "temperature-linear.yaml" in out
        assert "PASS" not in out and "FAIL" not in out
