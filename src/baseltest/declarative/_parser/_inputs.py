"""The ``inputs:`` block: scalars, flat lists, file-sourced parts, per-input ``expected:``.

An input is a JSON-expressible scalar, a flat list of scalars (splatted
positionally), or a **file-sourced part** — inline text, external text
(``text: {file: …}``), or a media reference (``audio:``/``image:``/
``document:``/``file:``). A media part resolves to a :class:`FileInput`
handed to a bound service; a text part resolves to the decoded ``str``.
An ``{input, expected}`` entry attaches per-input expectations, carrying
each input's structural position for attribution.
"""

import hashlib
from pathlib import Path
from typing import Any

from baseltest.contract import FileInput

from ._forms import _parse_form_entry
from ._model import Form, FormDeclaration
from ._shape import _fail, _require_mapping

_INPUT_SCALARS = (str, int, float, bool)

# The media kinds delivered to a bound service as a FileInput. `text` is
# handled separately — it resolves to a decoded str, never a FileInput.
_MEDIA_KEYS = ("file", "audio", "image", "document")
_PART_KEYS = ("text", *_MEDIA_KEYS)


def _resolve_and_read(raw_path: str, where: str, base_dir: Path | None) -> tuple[Path, bytes]:
    """Resolve a file-sourced part's path relative to the contract and read it.

    Resolution is relative to the contract file's directory, never the
    working directory. A file that cannot be read — absent, unreadable — is
    a load-time authoring error, surfaced before any invocation (so
    ``basel check`` catches it too).
    """
    if base_dir is None:
        raise _fail(
            f"{where}: a file-sourced input needs a contract loaded from disk to "
            f"resolve {raw_path!r} relative to it"
        )
    resolved = (base_dir / raw_path).resolve()
    try:
        data = resolved.read_bytes()
    except OSError as error:
        raise _fail(f"{where}: cannot read input file {resolved}: {error}") from error
    return resolved, data


def _text_part(value: Any, where: str, base_dir: Path | None) -> str:
    """A ``text:`` part — an inline string, or ``{file: <path>}`` decoded as UTF-8 text."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"file"} and isinstance(value["file"], str):
        _, data = _resolve_and_read(value["file"], where, base_dir)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _fail(f"{where}: `text:` file is not valid UTF-8 text: {error}") from error
    raise _fail(f"{where}: `text:` is a string or a `{{file: <path>}}` mapping")


def _media_part(kind: str, value: Any, where: str, base_dir: Path | None) -> FileInput:
    """A media part (``audio:``/``image:``/``document:``/``file:``) — a file path
    resolved to a :class:`FileInput`. The framework never interprets the bytes."""
    if not isinstance(value, str) or not value:
        raise _fail(f"{where}: `{kind}:` is a file path string")
    resolved, data = _resolve_and_read(value, where, base_dir)
    content_hash = hashlib.sha256(data).hexdigest()
    return FileInput(path=resolved, kind=kind, data=data, content_hash=content_hash)


def _part_mapping(mapping: dict[str, Any], where: str, base_dir: Path | None) -> Any:
    """A single-key input part mapping — text or a media reference."""
    if len(mapping) != 1:
        keys = ", ".join(sorted(mapping))
        raise _fail(
            f"{where}: an input part is a single-key mapping "
            f"({'/'.join(_PART_KEYS)}), got keys {{{keys}}} — a `{{input, expected}}` "
            "entry attaches expectations instead"
        )
    ((key, value),) = mapping.items()
    if key == "text":
        return _text_part(value, where, base_dir)
    if key in _MEDIA_KEYS:
        return _media_part(key, value, where, base_dir)
    raise _fail(
        f"{where}: unknown input part `{key}:` — a part is one of "
        f"{'/'.join(_PART_KEYS)}, or a `{{input, expected}}` entry"
    )


def _normalised_input(entry: Any, where: str, base_dir: Path | None) -> Any:
    """One input value: a scalar, a flat list of scalars, or a file-sourced part.

    Three list-free forms plus two list forms:

    - a scalar (string, number, boolean) — passed through;
    - a single-key mapping — a file-sourced part (``{audio: …}``,
      ``{text: {file: …}}``);
    - a flat list of *scalars* — a tuple splatted across the binding's
      positional parameters (unchanged);
    - a list of *parts* (single-key mappings) — the ordered-parts model; in
      this phase it must hold exactly one part, a multi-part input being
      reserved for the multimodal-gateway phase.
    """
    if isinstance(entry, _INPUT_SCALARS):
        return entry
    if isinstance(entry, dict):
        return _part_mapping(entry, where, base_dir)
    if isinstance(entry, list):
        if not entry:
            raise _fail(f"{where}: a list-valued input must be non-empty")
        if all(isinstance(item, _INPUT_SCALARS) for item in entry):
            return tuple(entry)
        if all(isinstance(item, dict) for item in entry):
            if len(entry) != 1:
                raise _fail(
                    f"{where}: a multi-part input (more than one part in one message) "
                    "is reserved for a later phase; give a single part"
                )
            return _part_mapping(entry[0], where, base_dir)
        raise _fail(
            f"{where}: a list-valued input is a flat list of scalars (splatted across "
            "the binding's parameters) or a list of parts (text/media), not a mix"
        )
    raise _fail(
        f"{where}: an input is a scalar, a flat list of scalars, or a file-sourced "
        f"part ({'/'.join(_PART_KEYS)}), got {type(entry).__name__}"
    )


def _parse_inputs(
    value: Any, views: dict[str, str], base_dir: Path | None
) -> tuple[tuple[Any, ...], tuple[tuple[int, Any, tuple[FormDeclaration, ...]], ...]]:
    if not isinstance(value, list) or not value:
        raise _fail("`inputs:` must be a non-empty list")
    inputs: list[Any] = []
    pairs: list[tuple[int, Any, tuple[FormDeclaration, ...]]] = []
    for index, entry in enumerate(value, start=1):
        where = f"inputs entry {index}"
        if not (isinstance(entry, dict) and set(entry) == {"input", "expected"}):
            inputs.append(_normalised_input(entry, where, base_dir))
            continue
        input_value = _normalised_input(entry["input"], where, base_dir)
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
