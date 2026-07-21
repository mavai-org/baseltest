"""Read-side of the baseline artefact: parsing and resolution.

The single-writer rule is untouched — reading is not writing. Because the
artefact is emitted by exactly one writer (:mod:`.writer`), the parser here
accepts precisely that emission grammar: two-space indentation, one
``key: value`` per line or one ``- item`` per line under a list key, every
string JSON-quoted. No third-party dependency; the scalars are JSON, the
structure is indentation.

Both artefact generations read back: ``baseltest-baseline-2`` (current)
and ``baseltest-baseline-1`` (no ``latency:`` block — a version-1 artefact
simply characterises the functional dimension only).

Resolution is strict identity of what was measured: same contract, same
inputs fingerprint, same covariates (the recorded provenance, minus the
volatile keys). A near-miss is reported with the reason it did not match —
a config drift must never silently downgrade a judged criterion.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from baseltest.engine import LatencyBasis

from .writer import SCHEMA_VERSION

_READABLE_SCHEMAS = frozenset({SCHEMA_VERSION, "baseltest-baseline-1"})

# Provenance keys that legitimately differ between the measure run and a
# later test run: they identify the run, not the thing measured.
_VOLATILE_PROVENANCE = frozenset({"runMode", "taskFile"})


@dataclass(frozen=True, slots=True)
class StoredCriterion:
    """One criterion's recorded evidence, as read back from the artefact."""

    successes: int
    trials: int


@dataclass(frozen=True, slots=True)
class StoredLatency:
    """The artefact's latency block, read back for bound derivation.

    The sorted vector is the payload a later test derives its bound from;
    the percentiles are the measurement run's descriptive summary.
    """

    basis: LatencyBasis
    contributing_samples: int
    total_samples: int
    percentiles: tuple[tuple[str, int], ...]
    sorted_passing_latencies_ms: tuple[int, ...]


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
    latency: StoredLatency | None = None


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
    """Parse the writer's emission grammar into nested mappings and lists.

    A ``key:`` line opens a nested container that starts as a mapping and
    becomes a list on its first ``- item`` line — the writer only ever
    emits homogeneous containers, so the switch is unambiguous.
    """
    root: dict[str, Any] = {}
    # (indent, container, parent, key-in-parent); the root has no parent.
    stack: list[tuple[int, Any, dict[str, Any] | None, str | None]] = [(0, root, None, None)]
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"malformed indentation: {raw!r}")
        line = raw.strip()
        while stack and stack[-1][0] > indent:
            stack.pop()
        top_indent, container, parent, parent_key = stack[-1]
        if line.startswith("- "):
            if isinstance(container, dict):
                if container or parent is None or parent_key is None:
                    raise ValueError(f"malformed list item: {raw!r}")
                container = []
                parent[parent_key] = container
                stack[-1] = (top_indent, container, parent, parent_key)
            container.append(json.loads(line[2:]))
        elif isinstance(container, list):
            raise ValueError(f"malformed line inside a list: {raw!r}")
        else:
            key, value_text = _split_entry(line)
            if value_text is None:
                child: dict[str, Any] = {}
                container[key] = child
                stack.append((indent + 2, child, container, key))
            else:
                container[key] = json.loads(value_text)
    return root


_DECODER = json.JSONDecoder()


def _split_entry(line: str) -> tuple[str, str | None]:
    """One emitted mapping line into its key and value text.

    Returns ``(key, None)`` for a block-opening ``key:`` line, otherwise
    ``(key, value_text)``. A JSON-quoted key is decoded, never searched
    for a separator: the key itself may contain ``": "`` (a
    failure-reason string quoting a regex, a covariate value).
    """
    if line.startswith('"'):
        try:
            key, end = _DECODER.raw_decode(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed line: {line!r}") from error
        rest = line[end:]
        if rest == ":":
            return str(key), None
        if rest.startswith(": ") and rest[2:]:
            return str(key), rest[2:]
        raise ValueError(f"malformed line: {line!r}")
    if line.endswith(":"):
        return line[:-1], None
    key, _, value_text = line.partition(": ")
    if not value_text:
        raise ValueError(f"malformed line: {line!r}")
    return key, value_text


def _parse_latency(body: dict[str, Any] | None) -> StoredLatency | None:
    if body is None:
        return None
    percentiles = tuple(
        (key, int(value))
        for key, value in body.items()
        if key.startswith("p") and key.endswith("Ms")
    )
    vector = tuple(int(v) for v in body.get("sortedPassingLatenciesMs", []))
    return StoredLatency(
        basis=LatencyBasis(body["basis"]),
        contributing_samples=int(body["contributingSamples"]),
        total_samples=int(body["totalSamples"]),
        percentiles=percentiles,
        sorted_passing_latencies_ms=vector,
    )


def read_baseline(path: Path) -> StoredBaseline:
    """Read one artefact back.

    Raises:
        ValueError: The file is not a readable baseline artefact (unknown
            schema generation, malformed emission).
        OSError: The file cannot be read.
    """
    data = _parse_lines(path.read_text(encoding="utf-8").splitlines())
    schema = data.get("schemaVersion")
    if schema not in _READABLE_SCHEMAS:
        readable = ", ".join(sorted(_READABLE_SCHEMAS))
        raise ValueError(f"{path.name}: schema {schema!r} is not one of: {readable}")
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
        latency=_parse_latency(data.get("latency")),
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
