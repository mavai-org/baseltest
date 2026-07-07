"""Read-side of the baseline artefact: parsing and resolution.

The single-writer rule is untouched — reading is not writing. Because the
artefact is emitted by exactly one writer (:mod:`.writer`), the parser here
accepts precisely that emission grammar: two-space indentation, one
``key: value`` per line, every string JSON-quoted. No third-party
dependency; the scalars are JSON, the structure is indentation.

Resolution is strict identity of what was measured: same contract, same
inputs fingerprint, same covariates (the recorded provenance, minus the
volatile keys). A near-miss is reported with the reason it did not match —
a config drift must never silently downgrade a judged criterion.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .writer import SCHEMA_VERSION

# Provenance keys that legitimately differ between the measure run and a
# later test run: they identify the run, not the thing measured.
_VOLATILE_PROVENANCE = frozenset({"runMode", "taskFile"})


@dataclass(frozen=True, slots=True)
class StoredCriterion:
    """One criterion's recorded evidence, as read back from the artefact."""

    successes: int
    trials: int


@dataclass(frozen=True, slots=True)
class StoredBaseline:
    """The artefact's content, read back for resolution and judgement."""

    path: Path
    contract_id: str
    sample_count: int
    inputs_identity: str
    generated_at: str
    provenance: dict[str, str]
    criteria: dict[str, StoredCriterion]


@dataclass(frozen=True, slots=True)
class BaselineResolution:
    """The outcome of looking for a matching baseline.

    Exactly one of ``baseline`` / ``reason`` is meaningful: a match carries
    the stored baseline; a non-match carries the honest reason.
    """

    baseline: StoredBaseline | None = None
    reason: str | None = None
    mismatched_keys: tuple[str, ...] = field(default=())

    @property
    def matched(self) -> bool:
        return self.baseline is not None


def _parse_lines(lines: list[str]) -> dict[str, Any]:
    """Parse the writer's emission grammar into nested mappings."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, root)]
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"malformed indentation: {raw!r}")
        line = raw.strip()
        while stack and stack[-1][0] > indent:
            stack.pop()
        container = stack[-1][1]
        if line.endswith(":"):
            key = _parse_key(line[:-1])
            child: dict[str, Any] = {}
            container[key] = child
            stack.append((indent + 2, child))
        else:
            key_part, _, value_part = line.partition(": ")
            if not value_part:
                raise ValueError(f"malformed line: {raw!r}")
            container[_parse_key(key_part)] = json.loads(value_part)
    return root


def _parse_key(token: str) -> str:
    return json.loads(token) if token.startswith('"') else token


def read_baseline(path: Path) -> StoredBaseline:
    """Read one artefact back.

    Raises:
        ValueError: The file is not a readable ``baseltest-baseline-1``
            artefact (wrong schema, malformed emission).
        OSError: The file cannot be read.
    """
    data = _parse_lines(path.read_text(encoding="utf-8").splitlines())
    schema = data.get("schemaVersion")
    if schema != SCHEMA_VERSION:
        raise ValueError(f"{path.name}: schema {schema!r} is not {SCHEMA_VERSION!r}")
    criteria: dict[str, StoredCriterion] = {}
    for name, body in data.get("criteria", {}).items():
        criteria[name] = StoredCriterion(
            successes=int(body["successes"]), trials=int(body["trials"])
        )
    provenance = {str(k): str(v) for k, v in data.get("provenance", {}).items()}
    return StoredBaseline(
        path=path,
        contract_id=str(data["contractId"]),
        sample_count=int(data["sampleCount"]),
        inputs_identity=str(data["inputsIdentity"]),
        generated_at=str(data.get("generatedAt", "")),
        provenance=provenance,
        criteria=criteria,
    )


def resolve_baseline(
    baseline_dir: Path,
    contract_id: str,
    inputs_identity: str,
    provenance: dict[str, str],
) -> BaselineResolution:
    """Find the baseline matching what this run would measure.

    Matching is strict identity: the deterministic filename locates the
    candidate (same contract, same inputs fingerprint), and the recorded
    covariates — the provenance minus volatile run-identity keys — must be
    equal. Any difference is a non-match, and the resolution says which
    keys differed: a drifted configuration is surfaced, never silently
    treated as "no baseline".
    """
    candidate = baseline_dir / f"{contract_id}-{inputs_identity[:12]}.yaml"
    if not candidate.is_file():
        return BaselineResolution(reason=f"no baseline found (expected {candidate.as_posix()})")
    try:
        stored = read_baseline(candidate)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return BaselineResolution(reason=f"baseline {candidate.name} is unreadable: {error}")
    if stored.inputs_identity != inputs_identity:
        return BaselineResolution(reason=f"baseline {candidate.name} records different inputs")
    theirs = {k: v for k, v in stored.provenance.items() if k not in _VOLATILE_PROVENANCE}
    ours = {k: v for k, v in provenance.items() if k not in _VOLATILE_PROVENANCE}
    if theirs != ours:
        differing = sorted(
            key for key in set(theirs) | set(ours) if theirs.get(key) != ours.get(key)
        )
        return BaselineResolution(
            reason=(
                f"baseline {candidate.name} was measured under a different "
                f"configuration (differing: {', '.join(differing)})"
            ),
            mismatched_keys=tuple(differing),
        )
    return BaselineResolution(baseline=stored)
