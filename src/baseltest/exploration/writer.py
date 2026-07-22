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
        - condition: "response is not valid JSON"
          count: 1
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

from baseltest.engine.artefact import factor_lines, quote
from baseltest.observation import RunObservation, observation_lines

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


# mavai-ref: JVI-8CHB31R — do not remove (resolves in mavai-orchestrator)
def render_exploration(record: RunObservation) -> str:
    """Serialise one configuration's record to the family schema, deterministically.

    Raises:
        ValueError: On a record with no criteria — a run always evaluates
            at least one criterion, and the schema binds the block.
    """
    if not record.criteria:
        raise ValueError("an exploration record carries at least one criterion")
    lines = [
        f"schemaVersion: {quote(SCHEMA_VERSION)}",
        f"serviceContractId: {quote(record.contract_id)}",
        f"configuration: {quote(exploration_stem(record.factors))}",
        f"generatedAt: {quote(record.generated_at.isoformat())}",
    ]
    # The block carries the full resolved configuration (constants
    # included) so one artefact tells the whole story; the filename
    # stem still derives from the discriminating factors alone.
    lines.extend(factor_lines(record.configuration or record.factors))
    lines.extend(observation_lines(record))
    return "\n".join(lines) + "\n"


def write_exploration(record: RunObservation, directory: Path) -> Path:
    """Write one configuration's artefact under ``directory/{contract}/``.

    Returns the written path. Filenames derive from the factor values, so
    re-running the same grid refreshes each configuration's file in place.
    """
    target = directory / record.contract_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{exploration_stem(record.factors)}.yaml"
    path.write_text(render_exploration(record), encoding="utf-8")
    return path
