"""Graduation: emit the equivalent contract as Python source the developer owns.

The emitted module is the contract the task file instantiates — the same
criteria, thresholds, transform, and run plan — expressed directly against
``baseltest.contract`` and ``baseltest.engine``. It is one-shot scaffolding:
after materialising, the source is the developer's; nothing round-trips.
"""

from ._parser import CriterionDeclaration, FormDeclaration, TaskDeclaration

_HEADER = '''"""Materialised from {task_file}: the contract the task file was running.

This is now your code. The task file instantiated exactly this contract;
edit it freely -- the declarative surface is no longer involved.
"""

from baseltest.contract import (
    Criterion,
    ServiceContract,
    ThresholdProvenance,
    contains,
    equals,
    matches,
    one_of,
    satisfies,
)
from baseltest.engine import Intent, RunKind, RunPlan, execute
from baseltest.reporting import render_run
'''


def _form_source(declaration: FormDeclaration) -> str:
    argument = declaration.argument
    if declaration.form == "equals":
        base = f"equals({str(argument)!r})"
    elif declaration.form == "contains":
        base = f"contains({str(argument)!r})"
    elif declaration.form == "matches":
        base = f"matches({str(argument)!r})"
    elif declaration.form == "one-of":
        base = f"one_of({[str(a) for a in argument]!r})"
    elif declaration.form == "satisfies":
        base = (
            f"satisfies({str(argument)!r}, {_identifier(str(argument))})"
            "  # TODO: import your registered predicate"
        )
    else:  # parses
        base = "satisfies('parses', lambda value: True)  # parseability via the transform"
    if declaration.path is not None:
        return (
            f"# TODO: path-qualified check (`path: {declaration.path}`): select with "
            "your JSONPath/XPath library of choice inside a satisfies() predicate\n"
            f"        {base}"
        )
    return base


def _identifier(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name)
    return cleaned or "check"


def _criterion_source(declaration: CriterionDeclaration) -> str:
    lines = ["    Criterion("]
    lines.append(f"        name={declaration.name!r},")
    lines.append("        postconditions=(")
    for form in declaration.forms:
        lines.append(f"            {_form_source(form)},")
    lines.append("        ),")
    if declaration.threshold is not None:
        lines.append(f"        threshold={declaration.threshold},")
    transform_name = declaration.transform or declaration.parses
    if transform_name is not None:
        lines.append(
            f"        # TODO: transform ({transform_name}): supply your own callable; "
            "raise TransformError for unparseable responses"
        )
    if declaration.threshold_origin or declaration.contract_ref:
        lines.append(
            "        provenance=ThresholdProvenance("
            f"origin={declaration.threshold_origin or 'unspecified'!r}, "
            f"contract_ref={declaration.contract_ref!r}),"
        )
    lines.append("    ),")
    return "\n".join(lines)


def materialise(declaration: TaskDeclaration) -> str:
    """Render the task declaration as a standalone Python module."""
    source = declaration.source_path.name if declaration.source_path else "a task file"
    parts = [_HEADER.format(task_file=source)]
    parts.append("\ndef invoke(value: str) -> str:")
    parts.append(
        f'    """TODO: your service call — the task file used the binding '
        f'{declaration.service!r}."""'
    )
    parts.append("    raise NotImplementedError\n")
    parts.append("\ncontract = ServiceContract(")
    parts.append(f"    contract_id={declaration.task!r},")
    parts.append("    invoke=invoke,")
    parts.append("    criteria=(")
    for criterion in declaration.criteria:
        parts.append(_criterion_source(criterion))
    parts.append("    ),")
    parts.append(")\n")
    parts.append("\nif __name__ == '__main__':")
    parts.append("    result = execute(contract, RunPlan(")
    parts.append(f"        samples={declaration.samples or 'None  # was derived'},")
    parts.append(f"        inputs={tuple(declaration.inputs)!r},")
    parts.append("    ))")
    parts.append("    print(render_run(result))")
    return "\n".join(parts) + "\n"
