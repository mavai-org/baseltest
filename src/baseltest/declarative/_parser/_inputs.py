"""The ``inputs:`` block: scalars, flat lists, and per-input ``expected:`` forms.

An input is a JSON-expressible scalar or a flat list of scalars (splatted
positionally); an ``{input, expected}`` entry attaches per-input
expectations, carrying each input's structural position for attribution.
"""

from typing import Any

from ._forms import _parse_form_entry
from ._model import Form, FormDeclaration
from ._shape import _fail, _require_mapping

_INPUT_SCALARS = (str, int, float, bool)


def _normalised_input(entry: Any, where: str) -> Any:
    """One input value: a scalar, or a flat list of scalars (one per parameter).

    A list becomes a tuple whose elements are splatted as the binding's
    positional arguments; nesting is refused — an input's values are
    JSON-expressible scalars, and interpreting one (a path, an identifier)
    is the service type's business, not the file format's.
    """
    if isinstance(entry, _INPUT_SCALARS):
        return entry
    if isinstance(entry, list):
        if not entry or not all(isinstance(item, _INPUT_SCALARS) for item in entry):
            raise _fail(
                f"{where}: a list-valued input must be a non-empty flat list of "
                "scalars (string, number, or boolean) — one value per service parameter"
            )
        return tuple(entry)
    raise _fail(
        f"{where}: an input is a scalar (string, number, or boolean) or a flat "
        f"list of scalars, got {type(entry).__name__}"
    )


def _parse_inputs(
    value: Any, views: dict[str, str]
) -> tuple[tuple[Any, ...], tuple[tuple[int, Any, tuple[FormDeclaration, ...]], ...]]:
    if not isinstance(value, list) or not value:
        raise _fail("`inputs:` must be a non-empty list")
    inputs: list[Any] = []
    pairs: list[tuple[int, Any, tuple[FormDeclaration, ...]]] = []
    for index, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            inputs.append(_normalised_input(entry, f"inputs entry {index}"))
            continue
        if set(entry) != {"input", "expected"}:
            raise _fail(
                "each `inputs:` entry is a scalar, a flat list of scalars, or an "
                "{input, expected} entry"
            )
        input_value = _normalised_input(entry["input"], f"inputs entry {index}")
        where = f"expected for input {input_value!r}"
        expected = entry["expected"]
        if isinstance(expected, dict):
            expected = [expected]
        if not isinstance(expected, list) or not expected:
            raise _fail(f"{where}: `expected:` is a form or a non-empty list of forms")
        forms = tuple(
            _parse_form_entry(_require_mapping(form_entry, where), where, views)
            for form_entry in expected
        )
        for declaration in forms:
            if declaration.form is Form.PARSES:
                raise _fail(f"{where}: `parses:` is a criterion-level form")
        # The input's position in the full input list — the structural
        # identity per-input checks carry (entries without `expected:`
        # occupy positions too, so the pair index alone would drift).
        pairs.append((len(inputs), input_value, forms))
        inputs.append(input_value)
    return tuple(inputs), tuple(pairs)
