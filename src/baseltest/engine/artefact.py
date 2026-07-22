"""Shared artefact-emission primitives: one deterministic YAML rendering.

Every baseltest artefact writer — baseline, exploration, optimization —
serialises to YAML by hand, deterministically and without a third-party
dependency: JSON-quoted strings are valid YAML flow scalars, numbers keep
their native YAML type, and key order is fixed, so identical records
produce identical bytes. The scalar, factor, and latency emitters that
realise that rendering are defined once here and shared by every writer,
rather than each writer carrying its own copy.

These are record-agnostic building blocks — a value, a factor mapping, a
latency block. The record-shaped compositions on top of them (a baseline's
criteria block, an experiment's observation block) live with the record
type they serialise, in the writer that owns it.
"""

import json
from typing import Any

from .latency import LatencyBlock
from .naming import bounded_key


def quote(value: str) -> str:
    """A YAML-safe scalar: JSON string quoting is valid YAML flow style."""
    return json.dumps(value, ensure_ascii=False)


def scalar(value: Any) -> str:
    """A value as a YAML scalar, native type preserved."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return quote(value)
    return quote(json.dumps(value, sort_keys=True, ensure_ascii=False))


def factor_lines(factors: tuple[tuple[str, Any], ...], indent: str = "") -> list[str]:
    """The ``factors:`` block: one configuration's resolved values."""
    if not factors:
        return []
    lines = [f"{indent}factors:"]
    for key, value in factors:
        lines.append(f"{indent}  {quote(bounded_key(key))}: {scalar(value)}")
    return lines


def latency_lines(latency: LatencyBlock, indent: str = "") -> list[str]:
    """The gated ``latency:`` block: basis, contributing counts, the
    supported percentiles, then the full ascending vector of passing-sample
    durations. Shared verbatim by the baseline and experiment artefacts."""
    lines = [
        f"{indent}latency:",
        f"{indent}  basis: {quote(latency.basis)}",
        f"{indent}  contributingSamples: {latency.contributing_samples}",
        f"{indent}  totalSamples: {latency.total_samples}",
    ]
    for key, value in latency.percentiles:
        lines.append(f"{indent}  {key}: {value}")
    if latency.sorted_passing_latencies_ms:
        lines.append(f"{indent}  sortedPassingLatenciesMs:")
        for duration in latency.sorted_passing_latencies_ms:
            lines.append(f"{indent}    - {duration}")
    return lines
