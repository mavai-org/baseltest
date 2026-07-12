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

from baseltest.baseline import BaselineResolution, resolve_baseline
from baseltest.contract import (
    PERCENTILE_LEVELS,
    Criterion,
    LatencyBar,
    LatencyBound,
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
from baseltest.engine import (
    Intent,
    RunKind,
    RunPlan,
    inputs_fingerprint,
    minimum_contributing_samples,
)
from baseltest.statistics import (
    bound_existence_minimum,
    check_feasibility,
    derive_latency_threshold,
    derive_sample_size_first,
)

from ._errors import ContractConfigurationError
from ._parser import (
    FORMAT_IDENTIFIER,
    RAW_VIEW,
    ContractDeclaration,
    CriterionDeclaration,
    FormDeclaration,
)
from ._providers import resolve_provider
from ._registry import has_binding, resolve_binding, resolve_check, resolve_transform
from ._services import (
    LanguageModelParameters,
    ServiceDefinition,
    configuration_values,
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
        result = inner.evaluate(subject)
        if result.passed:
            return result
        # Attribute the failure to its input: a per-input expectation's
        # reason is only diagnosable if it says which input it judged.
        reason = result.reason or f"postcondition {inner.name!r} not satisfied"
        return PostconditionResult.failed(f"for input {input_value!r}: {reason}")

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
        # A criterion-level `confidence:` overrides the contract-level one.
        confidence=declaration.confidence if declaration.confidence is not None else confidence,
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


# Sample sizing is decided at invocation, never in the file: the contract
# carries the claim, the invocation carries the budget.
DEFAULT_SAMPLES = 5
SILENT_DERIVATION_LIMIT = 100
RECOMMENDED_BASELINE_SAMPLES = 1000


@dataclass(frozen=True, slots=True)
class RunSizing:
    """A run's N and where the value came from — the run-plan line's data.

    Attributes:
        samples: The run's N (per configuration, for an explore run).
        provenance: ``"explicit"`` (a flag or API argument), ``"derived"``
            (the minimum the declared thresholds require), or
            ``"default"`` (the verb's fixed default).
        demanded_by: For a derived N, the criterion whose threshold set it.
        threshold: For a derived N, that criterion's threshold.
    """

    samples: int
    provenance: str
    demanded_by: str | None = None
    threshold: float | None = None


def _resolve_run_size(
    mode: RunKind,
    intent: str,
    samples: int | None,
    judged: Sequence[Criterion],
    samples_provenance: str | None = None,
) -> RunSizing:
    """The run's N: an explicit flag, or the verb's own sizing story.

    A test under validation intent derives its N from the claim — the
    largest per-criterion feasibility minimum — refusing a silently
    derived N above the limit (the gate binds the number nobody typed;
    an explicit flag of any size sails through; a risk-driven N computed
    from the operator's declared tolerance arrives with its own
    provenance). A smoke test gets the small fixed default. A measure
    gets no default at all: its budget is an experimental-design decision
    and must be typed.
    """
    if samples is not None:
        return RunSizing(samples=samples, provenance=samples_provenance or "explicit")
    if mode is RunKind.MEASURE:
        raise ContractConfigurationError(
            "a measure run's sample count is yours to choose — run with "
            f"`--samples N` ({RECOMMENDED_BASELINE_SAMPLES} is a solid "
            "baseline-grade count; a smaller deliberate budget is legitimate, "
            "and an empirical bar derived from a smaller baseline simply "
            "widens honestly)"
        )
    anchors = [
        (check_feasibility(1, c.threshold, c.confidence).minimum_samples, c)
        for c in judged
        if c.threshold is not None
    ]
    if intent == "verification" and anchors:
        minimum, criterion = max(anchors, key=lambda pair: pair[0])
        if minimum > SILENT_DERIVATION_LIMIT:
            raise ContractConfigurationError(
                f"criterion {criterion.name} (threshold {criterion.threshold}) "
                f"needs at least {minimum} samples — more than the "
                f"{SILENT_DERIVATION_LIMIT} this framework will derive silently. "
                f"Run it deliberately with `--samples {minimum}`, or declare "
                "`intent: smoke` for a cheap pass that renders no statistical "
                "verdict"
            )
        return RunSizing(
            samples=minimum,
            provenance="derived",
            demanded_by=criterion.name,
            threshold=criterion.threshold,
        )
    return RunSizing(samples=DEFAULT_SAMPLES, provenance="default")


def _latency_bar(
    declaration: ContractDeclaration,
    samples: int,
    resolution: BaselineResolution | None,
) -> LatencyBar | None:
    """The contract's latency bar, resolved to concrete bounds — or a refusal.

    Every refusal here fires before any service invocation: an asserted
    percentile the planned sample count can never estimate, an empirical
    declaration with no usable baseline, and a requested confidence the
    baseline's size cannot support a non-saturated bound at (the
    distribution-free existence condition) are all configuration facts,
    knowable up front.
    """
    spec = declaration.latency
    if spec is None:
        return None
    confidence = spec.confidence if spec.confidence is not None else declaration.confidence
    asserted = [percentile for percentile, _ in spec.ceilings] or list(spec.empirical)
    for percentile in asserted:
        minimum = minimum_contributing_samples(percentile)
        if minimum > samples:
            raise ContractConfigurationError(
                f"the latency bound on {percentile} needs at least {minimum} passing "
                f"samples to estimate, and the run is planned at {samples} — run with "
                f"`--samples {minimum}` or more (only passing samples contribute)"
            )

    if spec.ceilings:
        return LatencyBar(
            bounds=tuple(
                LatencyBound(percentile=percentile, threshold_ms=ms)
                for percentile, ms in spec.ceilings
            ),
            origin="explicit",
            confidence=confidence,
            provenance=ThresholdProvenance(
                origin=spec.threshold_origin or "unspecified",
                contract_ref=spec.contract_ref,
            ),
        )

    if resolution is None or not resolution.matched:
        reason = (
            resolution.reason
            if resolution is not None and resolution.reason
            else "no baseline was found"
        )
        raise ContractConfigurationError(
            f"empirical latency bounds derive from a measured baseline: {reason} — "
            "run `basel measure` first"
        )
    stored = resolution.baseline
    assert stored is not None
    if stored.latency is None or not stored.latency.sorted_passing_latencies_ms:
        raise ContractConfigurationError(
            f"baseline {stored.path.name} records no latency profile (it predates "
            "latency recording) — re-run `basel measure`"
        )
    vector = list(stored.latency.sorted_passing_latencies_ms)
    bounds = []
    for percentile in spec.empirical:
        derived = derive_latency_threshold(vector, PERCENTILE_LEVELS[percentile], confidence)
        if derived.saturated:
            required = bound_existence_minimum(PERCENTILE_LEVELS[percentile], confidence)
            raise ContractConfigurationError(
                f"no {confidence:.0%}-confident upper bound on {percentile} exists "
                f"from a baseline of {derived.n} passing samples — at least "
                f"{required} are needed. Re-measure with a larger budget, or declare "
                "a lower `latency: confidence:`"
            )
        bounds.append(
            LatencyBound(
                percentile=percentile,
                threshold_ms=round(derived.threshold),
                rank=derived.rank,
                baseline_percentile_ms=round(derived.baseline_percentile),
                baseline_samples=derived.n,
            )
        )
    return LatencyBar(
        bounds=tuple(bounds),
        origin="baseline-derived",
        confidence=confidence,
        provenance=ThresholdProvenance(origin="empirical", contract_ref=stored.path.name),
    )


@dataclass(frozen=True, slots=True)
class ExploreConfiguration:
    """One grid point, ready to run: its factors, contract instance, and plan.

    ``factors`` is the discriminating subset (grid keys that vary — names
    files and labels); ``configuration`` is the full resolved map the
    point runs under, recorded in its artefact.
    """

    parameters: LanguageModelParameters
    factors: dict[str, Any]
    configuration: dict[str, Any]
    contract: ServiceContract
    plan: RunPlan


def instantiate_explore(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None = None,
    samples_per_config: int | None = None,
) -> tuple[tuple[ExploreConfiguration, ...], RunSizing, tuple[str, ...]]:
    """Instantiate one runnable configuration per grid point for an explore run.

    An explore run is a measure run per configuration with a descriptive
    posture: every criterion participates, but thresholds are not
    consulted — the instantiated criteria carry no bar, so the engine
    characterises without judging, at any sample size. The per-configuration
    count is the invocation's (``--samples-per-config``), defaulting to a
    deliberately small figure — triage is small by design.

    A grid may span providers with differing structured-output support.
    Where measure and test refuse a schema an unsupporting provider cannot
    honour (population identity is load-bearing there), an exploration
    degrades honestly instead: the schema is not sent for that
    configuration, and the returned notes say so — the developer exploring
    across providers carries the output shape in the system prompt when
    the comparison should stay fair.

    Returns the configurations (baseline first), the run sizing, and the
    ``(note, ...)`` lines the caller should surface before running.

    Raises:
        ContractConfigurationError: The service resolves to a
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
    sizing = (
        RunSizing(samples=samples_per_config, provenance="explicit")
        if samples_per_config is not None
        else RunSizing(samples=DEFAULT_SAMPLES, provenance="default")
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
    notes: list[str] = []
    for parameters in definition.grid:
        if (
            parameters.response_schema is not None
            and not resolve_provider(parameters.provider).supports_response_schema
        ):
            # Announced degradation, never silent: the configuration that
            # actually runs — and its artefact — carries no schema.
            parameters = _replace(parameters, response_schema=None)
            notes.append(
                f"provider {parameters.provider!r} has no structured-output "
                "support in this reader — the response-schema is not sent for "
                "this configuration; carry the output shape in the system "
                "prompt if the comparison should stay fair"
            )
        contract = ServiceContract(
            contract_id=declaration.contract,
            invoke=_instrumented_invoke(language_model_invoker(parameters)),
            criteria=criteria,
            views=views,
        )
        plan = RunPlan(
            samples=sizing.samples,
            inputs=declaration.inputs,
            kind=RunKind.EXPLORE,
            intent=Intent.SMOKE,
        )
        configurations.append(
            ExploreConfiguration(
                parameters=parameters,
                factors=factor_values(definition, parameters),
                configuration=configuration_values(parameters),
                contract=contract,
                plan=plan,
            )
        )
    return tuple(configurations), sizing, tuple(notes)


def instantiate(
    declaration: ContractDeclaration,
    services: dict[str, ServiceDefinition] | None = None,
    mode: RunKind = RunKind.TEST,
    samples: int | None = None,
    baseline_dir: Path | None = None,
    samples_provenance: str | None = None,
) -> tuple[ServiceContract, RunPlan, RunSizing, dict[str, str], tuple[tuple[str, str], ...]]:
    """Instantiate the contract and plan for a contract declaration under a run mode.

    Returns the contract, the run plan, the run's sizing (N and its
    provenance — the run-plan line's data), the resolved service
    provenance, and — under ``test`` — the ``(name, reason)`` pairs for
    empirical criteria that could not be judged (no matching baseline).

    Under ``test``, a criterion without a declared threshold is an
    empirical criterion: when ``baseline_dir`` holds a matching baseline
    (same contract, inputs fingerprint, and covariates), its bar is derived
    from the baseline's recorded evidence at this run's own sample size —
    the companion's sample-size-first rule — and it is judged like its
    normative siblings, with provenance naming the artefact.

    Raises:
        ContractConfigurationError: On any load-time refusal — before any
            invocation. In particular, a ``test`` where nothing is
            judgeable, a silently derived N above the derivation gate's
            limit, and a ``measure`` without an explicit sample count.
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
        sizing = _resolve_run_size(mode, declaration.intent, samples, normative, samples_provenance)

        needs_baseline = bool(empirical_declared) or (
            declaration.latency is not None and bool(declaration.latency.empirical)
        )
        resolution = None
        if needs_baseline and baseline_dir is not None:
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
        latency_bar = _latency_bar(declaration, sizing.samples, resolution)

        empirical: list[Criterion] = []
        if empirical_declared:
            for entry in empirical_declared:
                if resolution is None or not resolution.matched:
                    reason = (
                        resolution.reason
                        if resolution is not None and resolution.reason
                        else "requires a baseline"
                    )
                    skipped.append((entry.name, f"{reason} — run `basel measure` first"))
                    continue
                stored = resolution.baseline
                assert stored is not None
                evidence = stored.criteria.get(entry.name)
                if evidence is None or evidence.trials == 0:
                    skipped.append(
                        (
                            entry.name,
                            f"baseline {stored.path.name} does not record this "
                            "criterion — re-run `basel measure`",
                        )
                    )
                    continue
                built = _build_criterion(entry, declaration.confidence, expected, transforms)
                derivation = derive_sample_size_first(
                    evidence.successes,
                    evidence.trials,
                    sizing.samples,
                    built.confidence,
                )
                empirical.append(
                    _replace(
                        built,
                        threshold=derivation.min_pass_rate,
                        cutoff=derivation.cutoff,
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
        sizing = _resolve_run_size(mode, declaration.intent, samples, criteria)
        # A declared latency bar is a test-time assertion; a measure run's
        # product — the baseline's latency profile — is what it derives from.
        latency_bar = None

    contract = ServiceContract(
        contract_id=declaration.contract,
        invoke=invoke,
        criteria=criteria,
        views=views,
        latency=latency_bar,
    )
    intent = Intent.VERIFICATION if declaration.intent == "verification" else Intent.SMOKE
    plan = RunPlan(samples=sizing.samples, inputs=declaration.inputs, kind=mode, intent=intent)
    return contract, plan, sizing, service_provenance, tuple(skipped)
