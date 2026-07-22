"""The single writer: serialising a baseline record to the artefact schema.

Schema ``baseltest-baseline-2`` (draft), emitted deterministically with no
third-party dependency: the schema is this package's own, every emitted
string is JSON-quoted (a JSON string is a valid YAML flow scalar), and key
order is fixed, so identical records produce identical bytes. Version 2
adds the ``latency:`` block — field-compatible with punit's baseline
latency block — to a version-1 body that is otherwise unchanged.

Illustrative artefact:

.. code-block:: yaml

    schemaVersion: "baseltest-baseline-2"
    contractId: "refund-confirmation"
    generatedAt: "2026-07-06T12:00:00+00:00"
    sampleCount: 300
    inputsIdentity: "3fd0..."
    provenance:
      taskFormat: "mavai-contract/1"
      binding: "refund-service"
    criteria:
      "relevant":
        observedPassRate: 0.98
        successes: 294
        trials: 300
        failureDistribution:
          "response does not contain 'refund'": 6
        normativeJudgement:
          state: "met"
          stipulatedThreshold: 0.95
          confidence: 0.95
    latency:
      basis: "passing-samples"
      contributingSamples: 294
      totalSamples: 300
      p50Ms: 240
      p90Ms: 480
      p95Ms: 760
      p99Ms: 1180
      sortedPassingLatenciesMs:
        - 118
        - 121
        # ... every contributing duration, ascending

The ``latency:`` block appears when at least one sample passed and carries
only the percentiles its contributing-sample count can support (p50 needs
1, p90 needs 10, p95 needs 20, p99 needs 100), followed by the full
ascending vector of passing-sample durations. The vector, not the
percentiles, is what a later test consumes to derive a latency bound at
its own confidence — nothing derived is persisted here.
"""

from pathlib import Path

from baseltest.engine.artefact import latency_lines, quote
from baseltest.engine.naming import bounded_key

from .record import BaselineRecord, CriterionCharacterisation

SCHEMA_VERSION = "baseltest-baseline-2"


def _criterion_lines(name: str, c: CriterionCharacterisation) -> list[str]:
    lines = [
        f"  {quote(bounded_key(name))}:",
        f"    observedPassRate: {c.observed_rate:.6f}",
        f"    successes: {c.successes}",
        f"    trials: {c.trials}",
    ]
    if c.failure_distribution:
        lines.append("    failureDistribution:")
        for reason in sorted(c.failure_distribution):
            lines.append(f"      {quote(bounded_key(reason))}: {c.failure_distribution[reason]}")
    if c.judgement is not None:
        lines.extend(
            [
                "    normativeJudgement:",
                f"      state: {quote(c.judgement.state)}",
                f"      stipulatedThreshold: {c.judgement.stipulated_threshold}",
                f"      confidence: {c.judgement.confidence}",
            ]
        )
    return lines


def render_baseline(record: BaselineRecord) -> str:
    """Serialise a record to the artefact schema, deterministically."""
    lines = [
        f"schemaVersion: {quote(SCHEMA_VERSION)}",
        f"contractId: {quote(record.contract_id)}",
        f"generatedAt: {quote(record.generated_at.isoformat())}",
        f"sampleCount: {record.sample_count}",
        f"inputsIdentity: {quote(record.inputs_identity)}",
    ]
    if record.provenance:
        lines.append("provenance:")
        for key in sorted(record.provenance):
            lines.append(f"  {quote(key)}: {quote(record.provenance[key])}")
    if record.views:
        lines.append("views:")
        for view in sorted(record.views):
            lines.append(f"  {quote(view)}:")
            lines.append(f"    outputSchemaFingerprint: {quote(record.views[view])}")
    lines.append("criteria:")
    for name, characterisation in record.criteria.items():
        lines.extend(_criterion_lines(name, characterisation))
    if record.latency is not None:
        lines.extend(latency_lines(record.latency))
    return "\n".join(lines) + "\n"


def baseline_filename(record: BaselineRecord) -> str:
    """The artefact's canonical filename: contract identity plus input-set tail.

    Stable per (contract, input set): re-measuring the same pairing
    refreshes the artefact rather than accumulating copies.
    """
    return f"{record.contract_id}-{record.inputs_identity[:12]}.yaml"


def write_baseline(record: BaselineRecord, directory: Path) -> Path:
    """Write the artefact under ``directory``, creating it if needed.

    Returns the written path. The artefact is on disk when this returns --
    callers that assert on results afterwards get persistence-before-
    assertion by construction.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / baseline_filename(record)
    path.write_text(render_baseline(record), encoding="utf-8")
    return path
