"""Instantiation: a validated task declaration into a live service contract and plan."""

from collections.abc import Callable, Sequence
from typing import Any

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
from baseltest.engine import Intent, RunKind, RunPlan, derive_minimum_samples

from ._errors import TaskConfigurationError
from ._parser import CriterionDeclaration, FormDeclaration, TaskDeclaration
from ._registry import resolve_binding, resolve_check, resolve_transform
from ._structured import (
    STOCK_TRANSFORMS,
    compile_jsonpath,
    compile_xpath,
    path_qualified,
)

_STRING_FORMS: dict[str, Callable[[Any], Postcondition]] = {
    "equals": lambda arg: equals(str(arg)),
    "contains": lambda arg: contains(str(arg)),
    "matches": lambda arg: matches(str(arg)),
    "one-of": lambda arg: one_of([str(item) for item in arg]),
}


def _parse_check_postcondition(transform_name: str) -> Postcondition:
    """The ``parses:`` sugar: the transform ran, nothing further to check."""
    return Postcondition(
        name=f"parses as {transform_name}",
        check=lambda _raw, _value: PostconditionResult.ok(),
    )


def _build_form(
    declaration: FormDeclaration, transform_name: str | None, where: str
) -> Postcondition:
    if declaration.form == "satisfies":
        name = str(declaration.argument)
        return satisfies(name, resolve_check(name))
    if declaration.form == "parses":
        return _parse_check_postcondition(str(declaration.argument))
    builder = _STRING_FORMS[declaration.form]
    inner = builder(declaration.argument)
    if declaration.path is None:
        return inner
    if transform_name in ("json", "yaml"):
        compiled = compile_jsonpath(declaration.path, where)
        return path_qualified("jsonpath", declaration.path, compiled, inner)
    if transform_name == "xml":
        expression = compile_xpath(declaration.path, where)
        return path_qualified("xpath", expression, expression, inner)
    raise TaskConfigurationError(
        f"{where}: `path:` requires a stock transform (json, xml, or yaml)"
    )


def _expected_pair_postcondition(
    pairs: Sequence[tuple[str, FormDeclaration]],
) -> Postcondition:
    """Per-input expectations: dispatch on the input at evaluation time."""
    checks = {
        input_value: _STRING_FORMS[declaration.form](declaration.argument)
        for input_value, declaration in pairs
    }

    def check(raw: str, _value: Any) -> PostconditionResult:
        current = _CURRENT_INPUT.get("value")
        expected = checks.get(current) if current is not None else None
        if expected is None:
            return PostconditionResult.ok()
        return expected.evaluate(raw, raw)

    return Postcondition(name="expected response per input", check=check)


# The engine evaluates postconditions on (response, value) without threading
# the input through; per-input expectation dispatch needs it. The runner sets
# the current input via the instrumented invoke below -- single-threaded per
# run by design.
_CURRENT_INPUT: dict[str, str] = {}


def _instrumented_invoke(invoke: Callable[[str], str]) -> Callable[[str], str]:
    def wrapped(value: str) -> str:
        _CURRENT_INPUT["value"] = value
        return invoke(value)

    return wrapped


def _build_criterion(
    declaration: CriterionDeclaration,
    confidence: float,
    expected_pairs: Sequence[tuple[str, FormDeclaration]],
) -> Criterion:
    where = f"criterion {declaration.name}"
    transform_name = declaration.transform or declaration.parses
    transform: Callable[[str], Any] | None = None
    if transform_name is not None:
        transform = STOCK_TRANSFORMS.get(transform_name) or resolve_transform(transform_name)

    postconditions = [_build_form(form, transform_name, where) for form in declaration.forms]
    if expected_pairs:
        postconditions.append(_expected_pair_postcondition(expected_pairs))

    provenance = ThresholdProvenance(
        origin=declaration.threshold_origin or "unspecified",
        contract_ref=declaration.contract_ref,
    )
    return Criterion(
        name=declaration.name,
        postconditions=tuple(postconditions),
        threshold=declaration.threshold,
        confidence=confidence,
        transform=transform,
        provenance=provenance,
    )


def instantiate(
    declaration: TaskDeclaration,
) -> tuple[ServiceContract, RunPlan, int | None]:
    """Instantiate the contract and plan a task declaration describes.

    Returns the contract, the run plan, and the derived sample count when
    ``samples`` was omitted (``None`` when it was declared).

    Raises:
        TaskConfigurationError: On any load-time refusal (unresolvable
            names, invalid expressions) — before any invocation.
    """
    invoke = _instrumented_invoke(resolve_binding(declaration.service))
    criteria = tuple(
        _build_criterion(entry, declaration.confidence, declaration.expected_pairs)
        for entry in declaration.criteria
    )
    contract = ServiceContract(contract_id=declaration.task, invoke=invoke, criteria=criteria)

    thresholded = any(criterion.is_thresholded for criterion in criteria)
    if declaration.kind == "measure":
        kind = RunKind.MEASURE
    elif declaration.kind == "test" or thresholded:
        kind = RunKind.TEST
    else:
        kind = RunKind.OBSERVATION

    derived: int | None = None
    samples = declaration.samples
    if samples is None:
        derived = derive_minimum_samples(contract)
        samples = derived

    intent = Intent.VERIFICATION if declaration.intent == "verification" else Intent.SMOKE
    plan = RunPlan(samples=samples, inputs=declaration.inputs, kind=kind, intent=intent)
    return contract, plan, derived
