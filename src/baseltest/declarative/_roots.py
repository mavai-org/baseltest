"""Named path anchors — the ``roots:`` block both declarative loaders share.

A file declares directory anchors once (``roots: {corpus: ../shared}``),
and every file-referencing position may reach through one with
``@<name>/…`` instead of encoding the file's own location into a
``../../..`` hop-chain. Roots are per-file: the contract file's and the
services file's roots are independent namespaces — nothing shared,
inherited, or discovered upward.

The ``MAVAI_ROOT_<NAME>`` environment variable (name uppercased, ``-`` →
``_``) replaces a declared value entirely and may be absolute — the
override is the machine-local channel, which keeps committed files free
of machine-local paths. It is read once per file load, never per sample.

Identity is untouched by design: file-sourced inputs fingerprint by
content, never by path, and a resolved system prompt is the covariate as
if written inline — a root changes only the path resolution ahead of the
read.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from ._errors import ContractConfigurationError

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def _fail(message: str) -> ContractConfigurationError:
    return ContractConfigurationError(message)


def _override_variable(name: str) -> str:
    return "MAVAI_ROOT_" + name.upper().replace("-", "_")


def _is_absolute(value: str) -> bool:
    """Every absolute spelling — POSIX and drive-letter alike."""
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


@dataclass(frozen=True, slots=True)
class RootDisclosure:
    """One root as provenance discloses it: the declared value and whether
    the environment overrode it — never the resolved override path
    (publication hygiene: artefacts must not embed machine-local paths)."""

    name: str
    declared: str
    overridden: bool


class Roots:
    """The file's resolved anchors, with used-name tracking for the
    dead-declaration refusal."""

    def __init__(self, anchors: dict[str, tuple[Path, str, bool]], file_what: str) -> None:
        self._anchors = anchors
        self._file_what = file_what
        self._used: set[str] = set()

    @staticmethod
    def parse(block: Any, base_dir: Path | None, file_what: str) -> "Roots":
        """Validate a ``roots:`` block and resolve each anchor.

        ``block`` is the raw top-level value (``None`` when the file
        declares no roots). Refusals surface at load, zero samples.
        """
        if block is None:
            return Roots({}, file_what)
        if not isinstance(block, dict) or not block:
            raise _fail(
                f"{file_what}: `roots:` must be a non-empty mapping of root "
                "names to relative directory paths — omit the block to "
                "declare no roots"
            )
        if base_dir is None:
            raise _fail(
                f"{file_what}: `roots:` needs a file loaded from disk — the "
                "anchors resolve relative to the declaring file's directory"
            )
        anchors: dict[str, tuple[Path, str, bool]] = {}
        for raw_name, raw_value in block.items():
            name = str(raw_name)
            if not _NAME_PATTERN.match(name):
                raise _fail(
                    f"{file_what}: root name {name!r} must match "
                    "[a-z][a-z0-9-]* — lower-case, digits, hyphens"
                )
            if not isinstance(raw_value, str) or not raw_value:
                raise _fail(
                    f"{file_what}: root `{name}:` declares no directory — its "
                    "value is a non-empty relative path"
                )
            if _is_absolute(raw_value):
                raise _fail(
                    f"{file_what}: root `{name}:` is absolute ({raw_value}) — "
                    "a declared root is relative to the declaring file; an "
                    f"absolute location is the {_override_variable(name)} "
                    "environment override's job"
                )
            override = os.environ.get(_override_variable(name))
            overridden = override is not None
            effective = override if override is not None else raw_value
            resolved = (
                Path(effective) if Path(effective).is_absolute() else base_dir / effective
            ).resolve()
            if not resolved.is_dir():
                raise _fail(
                    f"{file_what}: root `{name}:` resolves to {resolved}, "
                    "which is not an existing directory"
                    + (f" (via {_override_variable(name)})" if overridden else "")
                )
            anchors[name] = (resolved, raw_value, overridden)
        return Roots(anchors, file_what)

    def resolve(self, raw_path: str, where: str) -> Path | None:
        """The absolute location a ``@<name>/…`` reference names, or
        ``None`` when the path is not a root reference (a literal
        ``@``-initial filename is written ``./@…``)."""
        if not raw_path.startswith("@"):
            return None
        name, separator, remainder = raw_path[1:].partition("/")
        if not separator or not remainder:
            raise _fail(
                f"{where}: `{raw_path}` — a root is a directory; reference a "
                "file within it (`@" + name + "/<path>`)"
            )
        anchor = self._anchors.get(name)
        if anchor is None:
            declared = ", ".join(sorted(self._anchors)) or "none"
            raise _fail(
                f"{where}: `@{name}/` references an undeclared root — "
                f"{self._file_what} declares: {declared}"
            )
        root, _, _ = anchor
        resolved = (root / remainder).resolve()
        if not resolved.is_relative_to(root):
            raise _fail(
                f"{where}: `{raw_path}` escapes its root — the reference "
                f"resolves above `{name}:`; a path below the root needs no "
                "`..` climbing, and one above it belongs to a different root"
            )
        self._used.add(name)
        return resolved

    def refuse_dead(self) -> None:
        """A declared root referenced by nothing in the file is a dead
        declaration — most likely a leftover; remove it."""
        dead = sorted(set(self._anchors) - self._used)
        if dead:
            raise _fail(
                f"{self._file_what}: root `{dead[0]}:` is declared but "
                "referenced by nothing in the file — remove the dead "
                "declaration"
            )

    def disclosures(self) -> tuple[RootDisclosure, ...]:
        return tuple(
            RootDisclosure(name=name, declared=declared, overridden=overridden)
            for name, (_, declared, overridden) in sorted(self._anchors.items())
        )
