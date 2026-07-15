"""The exploration writer: the family's ``mavai-explore-1`` schema, one file per configuration.

Emission is deterministic (fixed key order, JSON-quoted strings — a JSON
string is a valid YAML flow scalar, and numbers keep their native YAML
type) so two artefacts from one grid diff cleanly: the lines that differ
are exactly the factor values and statistics that differ.

Filenames are human-readable stems derived from the configuration's
discriminating factor values — the developer reads the directory listing,
picks a pair, and diffs — with long values truncated and disambiguated by
a short content-hash suffix. The same stem travels in the body as the
``configuration:`` display name, so consumers never parse filenames.

Illustrative artefact:

.. code-block:: yaml

    schemaVersion: "mavai-explore-1"
    serviceContractId: "support-agent-tuning"
    configuration: "model-small-model_temperature-0.7"
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
    latency:
      basis: "passing-samples"
      contributingSamples: 4
      totalSamples: 5
      p50Ms: 480
      sortedPassingLatenciesMs:
        - 430
        - 460
        - 480
        - 510
    resultProjection:
      # ────── anchor:ac72368a ──────
      "sample[0]":
        inputIndex: 0
        postconditions:
          "answers-as-json": "passed"
        executionTimeMs: 480
        content: "{\"answer\": \"...\"}"

The ``latency:`` block appears when at least one sample passed and
carries only the percentiles its contributing-sample count can support
(p50 needs 5, p90 needs 10, p95 needs 20, p99 needs 100), followed by
the full ascending vector of passing-sample durations. The
``resultProjection:`` block records every sample — input index,
per-postcondition status (passed/failed/skipped), invocation duration,
and the response verbatim — with a content-deterministic diff anchor at
each sample boundary (first 8 hex of SHA-256 of "index:inputIndex") so
diffs between two artefacts of one grid align sample-by-sample.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .record import ExplorationRecord

SCHEMA_VERSION = "mavai-explore-1"

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
    """Serialise one configuration's record to the family schema, deterministically.

    Raises:
        ValueError: On a record with no criteria — a run always evaluates
            at least one criterion, and the schema binds the block.
    """
    if not record.criteria:
        raise ValueError("an exploration record carries at least one criterion")
    lines = [
        f"schemaVersion: {_quote(SCHEMA_VERSION)}",
        f"serviceContractId: {_quote(record.contract_id)}",
        f"configuration: {_quote(exploration_stem(record.factors))}",
        f"generatedAt: {_quote(record.generated_at.isoformat())}",
    ]
    rendered_factors = record.configuration or record.factors
    if rendered_factors:
        # The block carries the full resolved configuration (constants
        # included) so one artefact tells the whole story; the filename
        # stem still derives from the discriminating factors alone.
        lines.append("factors:")
        for key, value in rendered_factors:
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
    if record.latency is not None:
        lines.extend(
            [
                "latency:",
                f"  basis: {_quote(record.latency.basis)}",
                f"  contributingSamples: {record.latency.contributing_samples}",
                f"  totalSamples: {record.latency.total_samples}",
            ]
        )
        for key, value in record.latency.percentiles:
            lines.append(f"  {key}: {value}")
        if record.latency.sorted_passing_latencies_ms:
            lines.append("  sortedPassingLatenciesMs:")
            for duration in record.latency.sorted_passing_latencies_ms:
                lines.append(f"    - {duration}")
    if record.samples:
        lines.append("resultProjection:")
        for index, sample in enumerate(record.samples):
            # Content-deterministic diff anchor: same sample position and
            # input index → same anchor, so a diff between two artefacts of
            # one grid aligns at sample boundaries.
            anchor = hashlib.sha256(f"{index}:{sample.input_index}".encode()).hexdigest()[:8]
            lines.append(f"  # ────── anchor:{anchor} ──────")
            lines.append(f'  "sample[{index}]":')
            lines.append(f"    inputIndex: {sample.input_index}")
            lines.append("    postconditions:")
            for name, status in sample.postconditions:
                lines.append(f"      {_quote(name)}: {_quote(status)}")
            lines.append(f"    executionTimeMs: {sample.execution_time_ms}")
            lines.append(f"    content: {_quote(sample.content)}")
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
