"""The exploration writer: the family's ``punit-spec-1`` schema, one file per configuration.

Emission is deterministic (fixed key order, JSON-quoted strings — a JSON
string is a valid YAML flow scalar, and numbers keep their native YAML
type) so two artefacts from one grid diff cleanly: the lines that differ
are exactly the factor values and statistics that differ.

Filenames are human-readable stems derived from the configuration's
discriminating factor values — the developer reads the directory listing,
picks a pair, and diffs — with long values truncated and disambiguated by
a short content-hash suffix.

Illustrative artefact:

.. code-block:: yaml

    schemaVersion: "punit-spec-1"
    useCaseId: "support-agent-tuning"
    generatedAt: "2026-07-07T12:00:00+00:00"
    factors:
      "model": "small-model"
      "temperature": 0.7
    execution:
      samplesPlanned: 5
      samplesExecuted: 5
      terminationReason: "COMPLETED"
    statistics:
      observed: 0.800000
      successes: 4
      failures: 1
      failureDistribution:
        "response is not valid JSON": 1
      criteria:
        "answers-as-json":
          observedPassRate: 0.800000
          pass: 4
          fail: 1
          inconclusive: 0
    cost:
      totalTimeMs: 2500
      avgTimePerSampleMs: 500
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .record import ExplorationRecord

SCHEMA_VERSION = "punit-spec-1"

# Filename-stem rules: characters outside this set become underscores, and a
# value whose sanitised form exceeds the cap is truncated and suffixed with
# the first four hex characters of the SHA-256 of its full canonical form.
_STEM_VALUE_CAP = 32
_STEM_TRUNCATED_LENGTH = 24
_STEM_HASH_LENGTH = 4
_DISALLOWED = re.compile(r"[^A-Za-z0-9._-]")


def _canonical_value(value: Any) -> str:
    """A factor value's canonical string form."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return repr(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _sanitise(text: str) -> str:
    return re.sub(r"_+", "_", _DISALLOWED.sub("_", text))


def _stem_segment(key: str, value: Any) -> str:
    canonical = _canonical_value(value)
    sanitised = _sanitise(canonical)
    if len(sanitised) > _STEM_VALUE_CAP:
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_STEM_HASH_LENGTH]
        sanitised = f"{sanitised[:_STEM_TRUNCATED_LENGTH]}-{digest}"
    return f"{key}-{sanitised}"


def exploration_stem(factors: tuple[tuple[str, Any], ...]) -> str:
    """The human-readable filename stem for one configuration.

    One ``key-value`` segment per discriminating factor, joined with ``_``;
    a grid with a single point (no discriminating factors) is simply the
    baseline.
    """
    if not factors:
        return "baseline"
    return "_".join(_stem_segment(key, value) for key, value in factors)


def _quote(value: str) -> str:
    """A YAML-safe scalar: JSON string quoting is valid YAML flow style."""
    return json.dumps(value, ensure_ascii=False)


def _scalar(value: Any) -> str:
    """A factor value as a YAML scalar, native type preserved."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return _quote(value)
    return _quote(json.dumps(value, sort_keys=True, ensure_ascii=False))


# javai-ref: JVI-8CHB31R — do not remove (resolves in javai-orchestrator)
def render_exploration(record: ExplorationRecord) -> str:
    """Serialise one configuration's record to the family schema, deterministically."""
    lines = [
        f"schemaVersion: {_quote(SCHEMA_VERSION)}",
        f"useCaseId: {_quote(record.contract_id)}",
        f"generatedAt: {_quote(record.generated_at.isoformat())}",
    ]
    if record.factors:
        lines.append("factors:")
        for key, value in record.factors:
            lines.append(f"  {_quote(key)}: {_scalar(value)}")
    lines.extend(
        [
            "execution:",
            f"  samplesPlanned: {record.samples_planned}",
            f"  samplesExecuted: {record.samples_executed}",
            '  terminationReason: "COMPLETED"',
            "statistics:",
            f"  observed: {record.observed_rate:.6f}",
            f"  successes: {record.successes}",
            f"  failures: {record.samples_executed - record.successes}",
        ]
    )
    if record.failure_distribution:
        lines.append("  failureDistribution:")
        for reason in sorted(record.failure_distribution):
            lines.append(f"    {_quote(reason)}: {record.failure_distribution[reason]}")
    if record.criteria:
        lines.append("  criteria:")
        for name, statistics in record.criteria.items():
            lines.extend(
                [
                    f"    {_quote(name)}:",
                    f"      observedPassRate: {statistics.observed_rate:.6f}",
                    f"      pass: {statistics.passes}",
                    f"      fail: {statistics.fails}",
                    "      inconclusive: 0",
                ]
            )
    average = (
        round(record.total_time_ms / record.samples_executed) if record.samples_executed else 0
    )
    lines.extend(
        [
            "cost:",
            f"  totalTimeMs: {record.total_time_ms}",
            f"  avgTimePerSampleMs: {average}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_exploration(record: ExplorationRecord, directory: Path) -> Path:
    """Write one configuration's artefact under ``directory/{contract}/``.

    Returns the written path. Filenames derive from the factor values, so
    re-running the same grid refreshes each configuration's file in place.
    """
    target = directory / record.contract_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{exploration_stem(record.factors)}.yaml"
    path.write_text(render_exploration(record), encoding="utf-8")
    return path
