"""The ``optimizations:`` section: parsing and load-time validation.

Each entry declares one Optimize experiment over its service: which
stepper proposes configurations, which scorer judges an iteration, the
objective direction, and the termination controls. Everything checkable
without a sample is checked here — the same load-time-refusal posture as
the exploration grid, and what ``basel check`` runs for zero samples.

Iteration 0 is the baseline ``configuration:`` with the entry's
``initial:`` overrides applied; no ``initial:`` means iteration 0 is the
baseline itself. The overlay is partial, with exactly the merge semantics
of an exploration entry.
"""

import inspect
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from baseltest.optimization import Objective

from ._errors import ContractConfigurationError
from ._steppers import (
    ScorerFunction,
    StepFunction,
    StepperRegistration,
    bind_stepper_config,
)
from ._types import ServiceTypeContract

if TYPE_CHECKING:
    from ._registry import Registry

_ENTRY_KEYS = {
    "id",
    "stepper",
    "stepper-config",
    "scorer",
    "objective",
    "max-iterations",
    "no-improvement-window",
    "initial",
}
_DEFAULT_SCORER = "pass-rate"
_ID_SHAPE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class OptimizationDeclaration:
    """One resolved ``optimizations:`` entry, ready to run.

    Attributes:
        run_id: The entry's identity — the interchange ``experimentId``
            and the artefact filename.
        stepper_name: The registered stepper the entry names.
        stepper_config: The bound factory keyword arguments.
        step: The constructed step function (state, if the algorithm
            keeps any, lives in its factory's closure).
        scorer_name: The scorer the entry names (default ``pass-rate``).
        score: The resolved scorer function.
        objective: ``maximize`` or ``minimize``.
        max_iterations: Hard cap on iteration count.
        no_improvement_window: Plateau detection — stop after this many
            consecutive iterations without improvement; ``None`` means
            plateau detection is off and the run goes to the cap.
        initial: The raw ``initial:`` overlay, empty when absent.
        parameters: Iteration 0's parsed configuration — the baseline
            with the overlay applied.
        notes: Advisory lines the invocation should surface (never
            refusals — those raise).
    """

    run_id: str
    stepper_name: str
    stepper_config: dict[str, Any]
    step: StepFunction
    scorer_name: str
    score: ScorerFunction
    objective: Objective
    max_iterations: int
    no_improvement_window: int | None
    initial: dict[str, Any]
    parameters: Any
    notes: tuple[str, ...] = ()


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


def _positive_int(name: str, where: str, key: str, value: Any, required: bool) -> int | None:
    if value is None:
        if required:
            raise _fail(f"service {name!r}: {where}: `{key}:` is required")
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _fail(
            f"service {name!r}: {where}: `{key}:` must be a positive integer, got {value!r}"
        )
    return value


def _entry_id(name: str, where: str, entry: dict[str, Any], multiple: bool) -> str:
    run_id = entry.get("id")
    if run_id is None:
        if multiple:
            raise _fail(
                f"service {name!r}: {where}: `id:` is required when the service "
                "declares more than one optimization — each entry names its own "
                "run and artefact"
            )
        return name
    if not isinstance(run_id, str) or not _ID_SHAPE.match(run_id):
        raise _fail(
            f"service {name!r}: {where}: `id:` must be letters, digits, dots, "
            f"underscores, or hyphens (it names the artefact file), got {run_id!r}"
        )
    return run_id


def _resolve_stepper(
    name: str, where: str, entry: dict[str, Any], registry: "Registry"
) -> StepperRegistration:
    stepper_name = entry.get("stepper")
    if not isinstance(stepper_name, str) or not stepper_name:
        raise _fail(f"service {name!r}: {where}: `stepper:` is required — the registered name")
    registration = registry.find_stepper(stepper_name)
    if registration is None:
        registered = ", ".join(registry.registered_stepper_names())
        raise _fail(
            f"service {name!r}: {where}: unknown `stepper: {stepper_name}` — "
            f"registered steppers: {registered}{registry.closest_stepper_hint(stepper_name)} "
            "(built-in steppers ship with the framework; user steppers are "
            "registered in mavai-bindings.py with @bindings.stepper)"
        )
    return registration


def _resolve_scorer(
    name: str, where: str, entry: dict[str, Any], registry: "Registry"
) -> tuple[str, ScorerFunction]:
    scorer_name = entry.get("scorer", _DEFAULT_SCORER)
    if not isinstance(scorer_name, str) or not scorer_name:
        raise _fail(f"service {name!r}: {where}: `scorer:` must be a registered name")
    resolved = registry.find_scorer(scorer_name)
    if resolved is None:
        registered = ", ".join(registry.registered_scorer_names())
        raise _fail(
            f"service {name!r}: {where}: unknown `scorer: {scorer_name}` — "
            f"registered scorers: {registered} (user scorers are registered in "
            "mavai-bindings.py with @bindings.scorer)"
        )
    return scorer_name, resolved


def _resolve_objective(name: str, where: str, entry: dict[str, Any]) -> Objective:
    raw = entry.get("objective", Objective.MAXIMIZE.value)
    try:
        return Objective(raw)
    except ValueError:
        raise _fail(
            f"service {name!r}: {where}: `objective:` must be one of "
            f"{', '.join(o.value for o in Objective)}, got {raw!r}"
        ) from None


def _validate_configuration_keys(
    name: str,
    where: str,
    registration: StepperRegistration,
    kwargs: dict[str, Any],
    available_keys: tuple[str, ...],
) -> None:
    """Factory parameters that name configuration keys must name real ones."""
    signature = inspect.signature(registration.factory).parameters
    for parameter in registration.configuration_keys:
        value = kwargs.get(parameter)
        if value is None and parameter in signature:
            default = signature[parameter].default
            value = None if default is inspect.Parameter.empty else default
        if value is None:
            continue
        if value not in available_keys:
            available = ", ".join(available_keys)
            raise _fail(
                f"service {name!r}: {where}: stepper {registration.name!r} targets "
                f"configuration key {value!r}, which the configuration does not "
                f"declare — available keys: {available}"
            )


def _resolved_point(type_contract: ServiceTypeContract, parameters: Any) -> tuple[Any, ...]:
    """A configuration's identity: its resolved covariate values, nothing else."""
    return tuple(sorted(type_contract.provenance(parameters).items()))


def _iteration_zero(
    name: str,
    where: str,
    entry: dict[str, Any],
    baseline: dict[str, Any],
    type_contract: ServiceTypeContract,
) -> tuple[dict[str, Any], Any]:
    """Resolve the entry's ``initial:`` overlay into iteration 0's parameters."""
    initial = entry.get("initial")
    if initial is None:
        return {}, type_contract.parse(name, baseline, "configuration")
    if not isinstance(initial, dict) or not initial:
        raise _fail(
            f"service {name!r}: {where}: `initial:` must be a non-empty mapping of "
            "configuration values to replace for iteration 0 — omit it to start "
            "from the baseline"
        )
    for key, value in initial.items():
        if value is None:
            raise _fail(
                f"service {name!r}: {where}: `initial:` key `{key}:` declares no "
                "value — the overlay states replacements; omit a key to keep its "
                "baseline value"
            )
    merged = {**baseline, **initial}
    parameters = type_contract.parse(name, merged, f"{where} `initial:` overlay")
    baseline_parameters = type_contract.parse(name, baseline, "configuration")
    if _resolved_point(type_contract, parameters) == _resolved_point(
        type_contract, baseline_parameters
    ):
        raise _fail(
            f"service {name!r}: {where}: `initial:` merely restates values the "
            "configuration already holds — iteration 0 is the baseline by "
            "default; omit the overlay, or have it change something"
        )
    return dict(initial), parameters


def parse_optimizations(
    name: str,
    entries: Any,
    baseline: dict[str, Any],
    type_contract: ServiceTypeContract,
    registry: "Registry",
) -> tuple[OptimizationDeclaration, ...]:
    """Resolve the ``optimizations:`` entries — every load-time refusal fires here.

    Raises:
        ContractConfigurationError: The first entry that is not runnable
            as declared.
    """
    if not isinstance(entries, list) or not entries:
        raise _fail(
            f"service {name!r}: `optimizations:` must be a non-empty list of "
            "entries, each declaring one optimize run"
        )
    declarations: list[OptimizationDeclaration] = []
    seen_ids: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        where = f"optimization entry {index}"
        if not isinstance(entry, dict):
            raise _fail(f"service {name!r}: {where} must be a mapping")
        for key in entry:
            if key not in _ENTRY_KEYS:
                accepted = ", ".join(sorted(_ENTRY_KEYS))
                raise _fail(
                    f"service {name!r}: {where} has unknown key `{key}:` — an "
                    f"optimization entry accepts: {accepted}"
                )
        run_id = _entry_id(name, where, entry, multiple=len(entries) > 1)
        previous = seen_ids.get(run_id)
        if previous is not None:
            raise _fail(
                f"service {name!r}: {where}: `id: {run_id}` is already used by "
                f"{previous} — each optimization names its own run and artefact"
            )
        seen_ids[run_id] = where
        registration = _resolve_stepper(name, where, entry, registry)
        raw_config = entry.get("stepper-config", {})
        if not isinstance(raw_config, dict):
            raise _fail(
                f"service {name!r}: {where}: `stepper-config:` must be a mapping of "
                f"the stepper's factory parameters"
            )
        kwargs = bind_stepper_config(name, f"{where} `stepper-config:`", registration, raw_config)
        initial_overlay = entry.get("initial") if isinstance(entry.get("initial"), dict) else {}
        available_keys = tuple({**baseline, **(initial_overlay or {})})
        _validate_configuration_keys(name, where, registration, kwargs, available_keys)
        scorer_name, score = _resolve_scorer(name, where, entry, registry)
        objective = _resolve_objective(name, where, entry)
        max_iterations = _positive_int(
            name, where, "max-iterations", entry.get("max-iterations"), required=True
        )
        assert max_iterations is not None
        window = _positive_int(
            name, where, "no-improvement-window", entry.get("no-improvement-window"), required=False
        )
        notes: list[str] = []
        if window is not None and window >= max_iterations:
            notes.append(
                f"optimization {run_id!r}: no-improvement-window {window} cannot fire "
                f"within max-iterations {max_iterations} — plateau detection is inert; "
                "lower the window or raise the cap"
            )
        initial, parameters = _iteration_zero(name, where, entry, baseline, type_contract)
        step = registration.factory(**kwargs)
        declarations.append(
            OptimizationDeclaration(
                run_id=run_id,
                stepper_name=registration.name,
                stepper_config=kwargs,
                step=step,
                scorer_name=scorer_name,
                score=score,
                objective=objective,
                max_iterations=max_iterations,
                no_improvement_window=window,
                initial=initial,
                parameters=parameters,
                notes=tuple(notes),
            )
        )
    return tuple(declarations)
