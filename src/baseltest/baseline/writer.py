"""The single writer: serialising a baseline record to the artefact schema.

Schema ``baseltest-baseline-1`` (draft), emitted deterministically with no
third-party dependency: the schema is this package's own, every emitted
string is JSON-quoted (a JSON string is a valid YAML flow scalar), and key
order is fixed, so identical records produce identical bytes.

Illustrative artefact:

.. code-block:: yaml

    schemaVersion: "baseltest-baseline-1"
    contractId: "refund-confirmation"
    generatedAt: "2026-07-06T12:00:00+00:00"
    sampleCount: 300
    inputsIdentity: "3fd0..."
    provenance:
      taskFormat: "mavai-task/1"
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
"""

import json
from pathlib import Path

from .record import BaselineRecord, CriterionCharacterisation

SCHEMA_VERSION = "baseltest-baseline-1"


def _quote(value: str) -> str:
    """A YAML-safe scalar: JSON string quoting is valid YAML flow style."""
    return json.dumps(value, ensure_ascii=False)


def _criterion_lines(name: str, c: CriterionCharacterisation) -> list[str]:
    lines = [
        f"  {_quote(name)}:",
        f"    observedPassRate: {c.observed_rate:.6f}",
        f"    successes: {c.successes}",
        f"    trials: {c.trials}",
    ]
    if c.failure_distribution:
        lines.append("    failureDistribution:")
        for reason in sorted(c.failure_distribution):
            lines.append(f"      {_quote(reason)}: {c.failure_distribution[reason]}")
    if c.judgement is not None:
        lines.extend(
            [
                "    normativeJudgement:",
                f"      state: {_quote(c.judgement.state)}",
                f"      stipulatedThreshold: {c.judgement.stipulated_threshold}",
                f"      confidence: {c.judgement.confidence}",
            ]
        )
    return lines


def render_baseline(record: BaselineRecord) -> str:
    """Serialise a record to the artefact schema, deterministically."""
    lines = [
        f"schemaVersion: {_quote(SCHEMA_VERSION)}",
        f"contractId: {_quote(record.contract_id)}",
        f"generatedAt: {_quote(record.generated_at.isoformat())}",
        f"sampleCount: {record.sample_count}",
        f"inputsIdentity: {_quote(record.inputs_identity)}",
    ]
    if record.provenance:
        lines.append("provenance:")
        for key in sorted(record.provenance):
            lines.append(f"  {_quote(key)}: {_quote(record.provenance[key])}")
    lines.append("criteria:")
    for name, characterisation in record.criteria.items():
        lines.extend(_criterion_lines(name, characterisation))
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
