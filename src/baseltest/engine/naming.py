"""Artefact key discipline: bounded identities and structural per-input names.

The interchange formats bind every emitter to a key discipline: no mapping
key's content or length may depend on input or response content, every
emitted key stays within :data:`KEY_LIMIT` characters, and a longer key is
truncated under a defined rule — a bounded prefix plus a short content
hash, so truncated keys stay distinct. Per-input check identity is
structural — the condition's name plus the input's position in the input
list — never the input value; quoting input text is welcome only in
*values*, as bounded excerpts.

These helpers are the single home of that discipline: the declarative
layer names per-input postconditions through :func:`per_input_name`, the
record layer recovers the structural index through :func:`per_input_index`,
and every artefact writer bounds its free-text keys through
:func:`bounded_key` and its diagnostic quotes through
:func:`bounded_excerpt`.
"""

from __future__ import annotations

import hashlib
import re

KEY_LIMIT = 256
"""Emitted mapping keys and identity strings stay within this bound."""

EXCERPT_LIMIT = 256
"""Diagnostic excerpts of input or response text stay within this bound."""

_HASH_LENGTH = 12
_PER_INPUT_SUFFIX = re.compile(r" \(input (\d+)\)$")


def per_input_name(base: str, input_index: int) -> str:
    """A per-input check's structural identity: name plus input position."""
    return f"{base} (input {input_index})"


def per_input_index(name: str) -> int | None:
    """The structural input index a per-input name carries; ``None`` otherwise."""
    match = _PER_INPUT_SUFFIX.search(name)
    return int(match.group(1)) if match else None


def bounded_key(key: str, limit: int = KEY_LIMIT) -> str:
    """The key itself when within the bound; otherwise a distinct truncation.

    The truncation is a bounded prefix joined to a short content hash by
    ``#``, so two distinct over-long keys never collapse to one.
    """
    if len(key) <= limit:
        return key
    digest = hashlib.sha256(key.encode()).hexdigest()[:_HASH_LENGTH]
    return f"{key[: limit - _HASH_LENGTH - 1]}#{digest}"


def bounded_excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """The text itself when within the bound; otherwise an elided prefix."""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
