"""Graduation: emit the equivalent contract as Python source the developer owns.

The emitted module is the contract the contract file instantiates — the same
criteria, thresholds, views, and run plan — expressed directly against
``baseltest.contract`` and ``baseltest.engine``. It is one-shot scaffolding:
after materialising, the source is the developer's; nothing round-trips.
"""

from ._parser import ContractDeclaration, CriterionDeclaration, Form, FormDeclaration

_HEADER = '''"""Materialised from {contract_file}: the contract the contract file was running.

This is now your code. The contract file instantiated exactly this contract;
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
    if declaration.form is Form.EQUALS:
        base = f"equals({str(argument)!r})"
    elif declaration.form is Form.CONTAINS:
        base = f"contains({str(argument)!r})"
    elif declaration.form is Form.MATCHES:
        base = f"matches({str(argument)!r})"
    elif declaration.form is Form.ONE_OF:
        base = f"one_of({[str(a) for a in argument]!r})"
    elif declaration.form is Form.SATISFIES:
        base = (
            f"satisfies({str(argument)!r}, {_identifier(str(argument))})"
            "  # TODO: import your registered predicate"
        )
    else:  # parses
        base = (
            f"satisfies('parses as {argument}', lambda value: True, "
            f"view={str(argument)!r})  # forcing the view is the check"
        )
    if declaration.path is not None:
        return (
            f"# TODO: path-qualified check (`path: {declaration.path}` in view "
            f"{declaration.view!r}): select with your JSONPath/XPath library of "
            "choice inside a satisfies() predicate\n"
            f"        {base}"
        )
    if declaration.view != "raw" and declaration.form is not Form.PARSES:
        return base[:-1] + f", view={declaration.view!r})"
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
    if declaration.threshold_origin or declaration.contract_ref:
        lines.append(
            "        provenance=ThresholdProvenance("
            f"origin={declaration.threshold_origin or 'unspecified'!r}, "
            f"contract_ref={declaration.contract_ref!r}),"
        )
    lines.append("    ),")
    return "\n".join(lines)


# mavai-ref: JVI-CP4XG45 — do not remove (resolves in mavai-orchestrator)
def materialise(declaration: ContractDeclaration) -> str:
    """Render the contract declaration as a standalone Python module."""
    source = declaration.source_path.name if declaration.source_path else "a contract file"
    parts = [_HEADER.format(contract_file=source)]
    parts.append("\ndef invoke(value: str) -> str:")
    parts.append(
        f'    """TODO: your service call — the contract file used the binding '
        f'{declaration.service!r}."""'
    )
    parts.append("    raise NotImplementedError\n")
    parts.append("\ncontract = ServiceContract(")
    parts.append(f"    contract_id={declaration.contract!r},")
    parts.append("    invoke=invoke,")
    if declaration.transforms:
        parts.append("    views={")
        for view_name, transformation in declaration.transforms.items():
            parts.append(
                f"        {view_name!r}: ...,  # TODO: the {transformation} "
                "transformation -- supply your own callable; raise TransformError "
                "for unparseable responses"
            )
        parts.append("    },")
    parts.append("    criteria=(")
    for criterion in declaration.criteria:
        parts.append(_criterion_source(criterion))
    parts.append("    ),")
    parts.append(")\n")
    parts.append("\nif __name__ == '__main__':")
    parts.append("    result = execute(contract, RunPlan(")
    parts.append("        samples=100,  # TODO: size the run -- the budget is yours here too")
    parts.append(f"        inputs={tuple(declaration.inputs)!r},")
    parts.append("    ))")
    parts.append("    print(render_run(result))")
    return "\n".join(parts) + "\n"
