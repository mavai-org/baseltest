"""Deterministic emission of a run observation's YAML blocks.

The ``execution`` / ``statistics`` / ``cost`` / gated ``latency`` /
``resultProjection`` blocks a descriptive artefact carries for one
configuration's run — everything downstream of the ``factors:`` block,
rendered at a caller-chosen indent so the explore and optimize writers can
each embed it in their own schema.
"""

import hashlib

from baseltest.engine.artefact import latency_lines, quote
from baseltest.engine.naming import bounded_key

from .record import RunObservation


def observation_lines(record: RunObservation, indent: str = "") -> list[str]:
    """One configuration's descriptive observation blocks, shared by the
    experiment emitters: execution, statistics, cost, the gated latency
    block, and the result projection — everything downstream of the
    factors, rendered deterministically at the given indent."""
    lines = [
        f"{indent}execution:",
        f"{indent}  samplesPlanned: {record.samples_planned}",
        f"{indent}  samplesExecuted: {record.samples_executed}",
        f'{indent}  terminationReason: "COMPLETED"',
        f"{indent}statistics:",
        f"{indent}  observed: {record.observed_rate:.6f}",
        f"{indent}  successes: {record.successes}",
        f"{indent}  failures: {record.samples_executed - record.successes}",
    ]
    if record.failure_distribution:
        lines.append(f"{indent}  failureDistribution:")
        for entry in record.failure_distribution:
            lines.append(f"{indent}    - condition: {quote(entry.condition)}")
            if entry.input_index is not None:
                lines.append(f"{indent}      inputIndex: {entry.input_index}")
            if entry.input_excerpt is not None:
                lines.append(f"{indent}      inputExcerpt: {quote(entry.input_excerpt)}")
            lines.append(f"{indent}      count: {entry.count}")
    lines.append(f"{indent}  criteria:")
    for name, statistics in record.criteria.items():
        lines.extend(
            [
                f"{indent}    {quote(bounded_key(name))}:",
                f"{indent}      observedPassRate: {statistics.observed_rate:.6f}",
                f"{indent}      pass: {statistics.passes}",
                f"{indent}      fail: {statistics.fails}",
                f"{indent}      inconclusive: 0",
            ]
        )
    average = (
        round(record.total_time_ms / record.samples_executed) if record.samples_executed else 0
    )
    lines.extend(
        [
            f"{indent}cost:",
            f"{indent}  totalTimeMs: {record.total_time_ms}",
            f"{indent}  avgTimePerSampleMs: {average}",
        ]
    )
    if record.latency is not None:
        lines.extend(latency_lines(record.latency, indent))
    if record.samples:
        lines.append(f"{indent}resultProjection:")
        for index, sample in enumerate(record.samples):
            # Content-deterministic diff anchor: same sample position and
            # input index → same anchor, so a diff between two artefacts of
            # one grid aligns at sample boundaries.
            anchor = hashlib.sha256(f"{index}:{sample.input_index}".encode()).hexdigest()[:8]
            lines.append(f"{indent}  # ────── anchor:{anchor} ──────")
            lines.append(f'{indent}  "sample[{index}]":')
            lines.append(f"{indent}    inputIndex: {sample.input_index}")
            lines.append(f"{indent}    postconditions:")
            for name, status in sample.postconditions:
                lines.append(f"{indent}      {quote(bounded_key(name))}: {quote(status)}")
            lines.append(f"{indent}    executionTimeMs: {sample.execution_time_ms}")
            lines.append(f"{indent}    content: {quote(sample.content)}")
    return lines
