"""General multimodal assembly — the common machinery, no vendor shapes.

The provider-neutral parts of turning an input into request content: the
capability vocabulary, base64 / data-URI encoding, media-type derivation,
and the *skeleton* that decides text-only-vs-blocks. Each provider adapter
supplies its own API-specific block shape (a ``media_block`` renderer) and
composes it with :func:`content_blocks`; this module deliberately knows no
vendor's wire format.
"""

import base64
import mimetypes
from collections.abc import Callable
from typing import Any

from baseltest.contract import FileInput, MediaKind, MessageParts

# Single source: which capability token gates which media kind. `file` is a
# deliver-to-binding kind only — it has no model wire form, so it maps to no
# token and is refused at the LLM boundary.
CAPABILITY_FOR: dict[MediaKind, str] = {
    MediaKind.IMAGE: "image-input",
    MediaKind.DOCUMENT: "document-input",
    MediaKind.AUDIO: "audio-input",
}
MEDIA_CAPABILITY_NAMES: tuple[str, ...] = tuple(CAPABILITY_FOR.values())

# Per-kind media type when the file extension yields no guess.
_MIME_FALLBACK: dict[MediaKind, str] = {
    MediaKind.IMAGE: "image/png",
    MediaKind.DOCUMENT: "application/pdf",
    MediaKind.AUDIO: "audio/wav",
}

MediaBlock = Callable[[FileInput], dict[str, Any]]


def message_parts(user_input: Any) -> tuple[Any, ...]:
    """The ordered parts of an LLM input; a lone str/FileInput is one part."""
    if isinstance(user_input, MessageParts):
        return user_input.parts
    return (user_input,)


def media_kinds_present(user_input: Any) -> frozenset[MediaKind]:
    """The distinct media kinds an input carries (empty for text-only)."""
    return frozenset(p.kind for p in message_parts(user_input) if isinstance(p, FileInput))


def has_media(user_input: Any) -> bool:
    return any(isinstance(p, FileInput) for p in message_parts(user_input))


def mime_type(part: FileInput) -> str:
    """The media type from the file extension, with a per-kind fallback."""
    guess, _ = mimetypes.guess_type(part.path.name)
    return guess or _MIME_FALLBACK.get(part.kind, "application/octet-stream")


def b64(part: FileInput) -> str:
    """The part's bytes as base64 ASCII — the raw form vendors embed."""
    return base64.b64encode(part.data).decode("ascii")


def data_uri(part: FileInput) -> str:
    """A ``data:<mime>;base64,<...>`` URI — the form OpenAI-style APIs embed."""
    return f"data:{mime_type(part)};base64,{b64(part)}"


def unexpected_kind(part: FileInput, protocol: str) -> RuntimeError:
    """A defect (not an authoring error) for a block renderer that meets a kind
    its protocol does not carry — the media preflight should have refused it."""
    return RuntimeError(
        f"{protocol} block assembly reached an unsupported media kind "
        f"{part.kind!r} — the media capability preflight failed to refuse it"
    )


def content_blocks(user_input: Any, media_block: MediaBlock) -> Any:
    """The general text-vs-blocks skeleton for a block-based protocol.

    The plain input when there is no media — byte-identical to a text-only
    request, so existing contracts are untouched — otherwise an ordered list
    of typed blocks, text and media interleaved in the authored order. The
    text block shape (``{"type": "text", ...}``) is common to the block-based
    protocols; the ``media_block`` renderer is the adapter's own.
    """
    if not has_media(user_input):
        return user_input
    return [
        {"type": "text", "text": part} if isinstance(part, str) else media_block(part)
        for part in message_parts(user_input)
    ]
