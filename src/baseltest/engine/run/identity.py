"""Input identity: a stable, order-insensitive fingerprint of an input list."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from baseltest.contract import FileInput, MessageParts


def _canonical_entry(entry: Any) -> Any:
    """A JSON-serialisable canonical form for one input entry.

    A file-sourced input contributes its **content** — via its content
    hash and kind — never its path, so a file that drifts behind a stable
    path yields a different fingerprint. A multi-part input canonicalises
    each part in order (message order is significant, unlike the outer
    input list). A text part is already a plain string and needs no
    wrapping.
    """
    if isinstance(entry, FileInput):
        return {"file": entry.identity()}
    if isinstance(entry, MessageParts):
        return {"parts": [_canonical_entry(part) for part in entry.parts]}
    if isinstance(entry, tuple):
        return list(entry)
    return entry


def inputs_fingerprint(inputs: Sequence[Any]) -> str:
    """A stable, order-insensitive fingerprint of an input list.

    All-string lists keep their historical canonical form, so existing
    baselines stay addressable; mixed or structured inputs (tuples,
    file-sourced parts) canonicalise each entry before sorting.
    """
    if all(isinstance(entry, str) for entry in inputs):
        canonical = json.dumps(sorted(inputs), ensure_ascii=False)
    else:
        encoded = sorted(json.dumps(_canonical_entry(e), ensure_ascii=False) for e in inputs)
        # An object wrapper, so a structured corpus can never collide with
        # the historical all-string array form.
        canonical = json.dumps({"typed-inputs": encoded}, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
