"""Instantiation: a validated contract declaration into a live service contract and plan.

The run mode is supplied by the invocation (the verb), never by the file:
``test`` instantiates a probabilistic test over the thresholded criteria
(criteria without a bar are skipped, reported by name — never silently);
``measure`` instantiates a measure experiment over every criterion.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any

from baseltest.baseline import resolve_baseline
from baseltest.contract import (
    Criterion,
    Postcondition,
    PostconditionResult,
    ServiceContract,
    ThresholdProvenance,
    contains,
    equals,
    matches,
    one_of,
    satisfies,
)
from baseltest.engine import Intent, RunKind, RunPlan, derive_minimum_samples, inputs_fingerprint
from baseltest.statistics import derive_sample_size_first

from ._errors import ContractConfigurationError
from ._parser import (
    FORMAT_IDENTIFIER,
    RAW_VIEW,
    ContractDeclaration,
    CriterionDeclaration,
    FormDeclaration,
)
from ._registry import has_binding, resolve_binding, resolve_check, resolve_transform
from ._services import (
    LanguageModelParameters,
    ServiceDefinition,
    factor_values,
    language_model_invoker,
    resolved_provenance,
)
from ._structured import STOCK_TRANSFORMS as STOCK_TRANSFORM_FNS
from ._structured import compile_jsonpath, compile_xpath, path_qualified

_STRING_FORMS: dict[str, Callable[..., Postcondition]] = {
    "equals": lambda arg, view: equals(str(arg), view=view),
    "contains": lambda arg, view: contains(str(arg), view=view),
    "matches": lambda arg, view: matches(str(arg), view=view),
    "one-of": lambda arg, view: one_of([str(item) for item in arg], view=view),
}


def _build_views(declaration: ContractDeclaration) -> dict[str, Callable[[str], Any]]:
    views: dict[str, Callable[[str], Any]] = {}
    for view_name, transformation in declaration.transforms.items():
        views[view_name] = STOCK_TRANSFORM_FNS.get(transformation) or resolve_transform(
            transformation
        )
    return views


def _parses_postcondition(view: str) -> Postcondition:
    """``parses: <view>``: forcing the view's computation is the whole check."""
    return Postcondition(
        name=f"parses as {view}",
        check=lambda _subject: PostconditionResult.ok(),
        view=view,
    )


def _build_form(
    declaration: FormDeclaration, transforms: dict[str, str], where: str
) -> Postcondition:
    if declaration.form == "satisfies":
        name = str(declaration.argument)
        return satisfies(name, resolve_check(name), view=declaration.view)
    if declaration.form == "parses":
        return _parses_postcondition(str(declaration.argument))
    builder = _STRING_FORMS[declaration.form]
    if declaration.path is None:
        return builder(declaration.argument, declaration.view)
    inner = builder(declaration.argument, RAW_VIEW)
    transformation = transforms.get(declaration.view)
    if transformation in ("json", "yaml"):
        compiled = compile_jsonpath(declaration.path, where)
        return path_qualified("jsonpath", declaration.path, compiled, inner, view=declaration.view)
    if transformation == "xml":
        expression = compile_xpath(declaration.path, where)
        return path_qualified("xpath", expression, expression, inner, view=declaration.view)
    raise ContractConfigurationError(
        f"{where}: `path:` requires a view with a stock transformation"
    )


def _expected_postconditions(
    pairs: Sequence[tuple[str, tuple[FormDeclaration, ...]]],
    transforms: dict[str, str],
) -> list[Postcondition]:
    """Per-input expectations: each check dispatches on the trial's input."""
    dispatching: list[Postcondition] = []
    for input_value, declarations in pairs:
        for declaration in declarations:
            where = f"expected for input {input_value!r}"
            inner = _build_form(declaration, transforms, where)
            dispatching.append(_dispatch_on_input(input_value, inner))
    return dispatching


def _dispatch_on_input(input_value: str, inner: Postcondition) -> Postcondition:
    def check(subject: Any) -> PostconditionResult:
        if _CURRENT_INPUT.get("value") != input_value:
            return PostconditionResult.ok()
        return inner.evaluate(subject)

    return Postcondition(
        name=f"{inner.name} (for input {input_value!r})", check=check, view=inner.view
    )


# The engine evaluates postconditions without threading the input through;
# per-input dispatch needs it. The instrumented invoke below records the
# current input -- single-threaded per run by design.
_CURRENT_INPUT: dict[str, str] = {}


def _instrumented_invoke(invoke: Callable[[str], str]) -> Callable[[str], str]:
    def wrapped(value: str) -> str:
        _CURRENT_INPUT["value"] = value
        return invoke(value)

    return wrapped


def _build_criterion(
    declaration: CriterionDeclaration,
    confidence: float,
    expected: Sequence[Postcondition],
    transforms: dict[str, str],
) -> Criterion:
    where = f"criterion {declaration.name}"
    postconditions = [_build_form(form, transforms, where) for form in declaration.forms]
    postconditions.extend(expected)
    provenance = ThresholdProvenance(
        origin=declaration.threshold_origin or "unspecified",
        contract_ref=declaration.contract_ref,
    )
    return Criterion(
        name=declaration.name,
        postconditions=tuple(postconditions),
        threshold=declaration.threshold,
        confidence=confidence,
        provenance=provenance,
    )


def _resolve_service(
    reference: str, services: dict[str, ServiceDefinition]
) -> tuple[Callable[[str], str], dict[str, str]]:
    """Resolve a service reference against both registry populations."""
    defined = reference in services
    registered = has_binding(reference)
    if defined and registered:
        raise ContractConfigurationError(
            f"service {reference!r} is both registered in code (@binding) and defined "
            "in the services file — one name, one owner; rename one of them"
        )
    if defined:
        parameters = services[reference].configuration
        return language_model_invoker(parameters), resolved_provenance(parameters)
    return resolve_binding(reference), {}


def _resolve_run_size(
    declaration: ContractDeclaration,
    samples: int | None,
    judged: Sequence[Criterion],
    views: dict[str, Any],
    invoke: Callable[[str], str],
) -> tuple[int, int | None]:
    """The run's N: invocation override, then the file, then derivation."""
    if samples is not None:
        return samples, None
    if declaration.samples is not None:
        return declaration.samples, None
    anchors = [c for c in judged if c.threshold is not None]
    if not anchors:
        raise ContractConfigurationError(
            "`samples:` is required here — with no declared bar there is no "
            "feasibility anchor to derive a sample count from"
        )
    probe = ServiceContract(
        contract_id=declaration.contract, invoke=invoke, criteria=tuple(anchors), views=views
    )
    derived = derive_minimum_samples(probe)
    return derived, derived


@dataclass(frozen=True, slots=True)
class ExploreConfiguration:
    """One grid point, ready to run: its factors, contract instance, and plan."""

    parameters: LanguageModelParameters
    factors: dict[str, Any]
    contract: ServiceContract
    plan: RunPlan


def instantiate_explore(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None = None,
) -> tuple[ExploreConfiguration, ...]:
    """Instantiate one runnable configuration per grid point for an explore run.

    An explore run is a measure run per configuration with a descriptive
    posture: every criterion participates, but thresholds are not
    consulted — the instantiated criteria carry no bar, so the engine
    characterises without judging, at any sample size.

    Raises:
        ContractConfigurationError: The contract file declares no
            ``samples-per-config:`` (a pure characterisation has no anchor
            to derive a count from), or the service resolves to a
            code-registered binding — explore currently requires a service
            declared in the services file, whose configuration grid is the
            factor source.
    """
    definition = (services or {}).get(declaration.service)
    if definition is None:
        if has_binding(declaration.service):
            raise ContractConfigurationError(
                f"explore requires a declared service: {declaration.service!r} is "
                "registered in code (@binding), and a code binding carries no "
                "configuration grid to explore — declare the service (and its "
                "`explorations:` entries) in the services file"
            )
        resolve_binding(declaration.service)  # raises the standard unresolvable refusal
        raise AssertionError("unreachable: resolve_binding refuses unknown names")
    if declaration.samples_per_config is None:
        raise ContractConfigurationError(
            "`samples-per-config:` is required for an explore run — exploration "
            "is a pure characterisation per configuration, so the sample count "
            "is yours to choose (any positive number; small counts are the point)"
        )
    transforms = declaration.transforms
    views = _build_views(declaration)
    expected = _expected_postconditions(declaration.expected_pairs, transforms)
    criteria = tuple(
        _replace(
            _build_criterion(entry, declaration.confidence, expected, transforms),
            threshold=None,
        )
        for entry in declaration.criteria
    )
    configurations = []
    for parameters in definition.grid:
        contract = ServiceContract(
            contract_id=declaration.contract,
            invoke=_instrumented_invoke(language_model_invoker(parameters)),
            criteria=criteria,
            views=views,
        )
        plan = RunPlan(
            samples=declaration.samples_per_config,
            inputs=declaration.inputs,
            kind=RunKind.EXPLORE,
            intent=Intent.SMOKE,
        )
        configurations.append(
            ExploreConfiguration(
                parameters=parameters,
                factors=factor_values(definition, parameters),
                contract=contract,
                plan=plan,
            )
        )
    return tuple(configurations)


def instantiate(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None = None,
    mode: RunKind = RunKind.TEST,
    samples: int | None = None,
    baseline_dir: Path | None = None,
) -> tuple[ServiceContract, RunPlan, int | None, dict[str, str], tuple[tuple[str, str], ...]]:
    """Instantiate the contract and plan for a contract declaration under a run mode.

    Returns the contract, the run plan, the derived sample count when the
    size was derived, the resolved service provenance, and — under ``test``
    — the ``(name, reason)`` pairs for empirical criteria that could not be
    judged (no matching baseline).

    Under ``test``, a criterion without a declared threshold is an
    empirical criterion: when ``baseline_dir`` holds a matching baseline
    (same contract, inputs fingerprint, and covariates), its bar is derived
    from the baseline's recorded evidence at this run's own sample size —
    the companion's sample-size-first rule — and it is judged like its
    normative siblings, with provenance naming the artefact.

    Raises:
        ContractConfigurationError: On any load-time refusal — before any
            invocation. In particular, a ``test`` where nothing is
            judgeable, and a threshold-less ``measure`` with no ``samples``.
    """
    resolved, service_provenance = _resolve_service(declaration.service, services or {})
    invoke = _instrumented_invoke(resolved)
    transforms = declaration.transforms
    views = _build_views(declaration)
    expected = _expected_postconditions(declaration.expected_pairs, transforms)

    skipped: list[tuple[str, str]] = []
    if mode is RunKind.TEST:
        normative = [
            _build_criterion(entry, declaration.confidence, expected, transforms)
            for entry in declaration.criteria
            if entry.threshold is not None
        ]
        empirical_declared = [c for c in declaration.criteria if c.threshold is None]
        run_size, derived = _resolve_run_size(declaration, samples, normative, views, invoke)

        empirical: list[Criterion] = []
        if empirical_declared:
            resolution = None
            if baseline_dir is not None:
                resolution = resolve_baseline(
                    baseline_dir,
                    declaration.contract,
                    inputs_fingerprint(declaration.inputs),
                    {
                        "taskFormat": FORMAT_IDENTIFIER,
                        "binding": declaration.service,
                        **service_provenance,
                    },
                )
            for entry in empirical_declared:
                if resolution is None or not resolution.matched:
                    reason = (
                        resolution.reason
                        if resolution is not None and resolution.reason
                        else "requires a baseline"
                    )
                    skipped.append((entry.name, f"{reason} — run `baseltest measure` first"))
                    continue
                stored = resolution.baseline
                assert stored is not None
                evidence = stored.criteria.get(entry.name)
                if evidence is None or evidence.trials == 0:
                    skipped.append(
                        (
                            entry.name,
                            f"baseline {stored.path.name} does not record this "
                            "criterion — re-run `baseltest measure`",
                        )
                    )
                    continue
                derivation = derive_sample_size_first(
                    evidence.successes,
                    evidence.trials,
                    run_size,
                    declaration.confidence,
                )
                built = _build_criterion(entry, declaration.confidence, expected, transforms)
                empirical.append(
                    _replace(
                        built,
                        threshold=derivation.min_pass_rate,
                        provenance=ThresholdProvenance(
                            origin="empirical", contract_ref=stored.path.name
                        ),
                    )
                )
        criteria = tuple(normative + empirical)
        if not criteria:
            detail = f" ({skipped[0][1]})" if skipped else ""
            raise ContractConfigurationError(
                "nothing to test: no criterion declares a `threshold:` and no "
                f"empirical criterion could be judged{detail}. Run `baseltest "
                "measure` to establish a baseline, or declare a bar."
            )
    else:
        criteria = tuple(
            _build_criterion(entry, declaration.confidence, expected, transforms)
            for entry in declaration.criteria
        )
        run_size, derived = _resolve_run_size(declaration, samples, criteria, views, invoke)

    contract = ServiceContract(
        contract_id=declaration.contract, invoke=invoke, criteria=criteria, views=views
    )
    intent = Intent.VERIFICATION if declaration.intent == "verification" else Intent.SMOKE
    plan = RunPlan(samples=run_size, inputs=declaration.inputs, kind=mode, intent=intent)
    return contract, plan, derived, service_provenance, tuple(skipped)
