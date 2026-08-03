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

import hashlib
import json
from pathlib import Path

from baseltest.engine.artefact import latency_lines, quote
from baseltest.engine.naming import bounded_excerpt, bounded_key

from .record import BaselineRecord, CriterionCharacterisation, CriterionMode

SCHEMA_VERSION = "mavai-baseline-1"
FINGERPRINT_KEY = "contentFingerprint"


def _criterion_lines(name: str, c: CriterionCharacterisation) -> list[str]:
    lines = [
        f"  {quote(bounded_key(name))}:",
        f"    mode: {quote(c.mode)}",
    ]
    if c.procedure is not None:
        lines.append(f"    procedure: {quote(c.procedure)}")
    lines.extend([f"    trials: {c.trials}", f"    successes: {c.successes}"])
    if c.mode is CriterionMode.INFERENTIAL:
        # Not stateable at zero trials, and stating 0.0 would assert a rate
        # from the same non-evidence that makes the bound null — absence and
        # "0%" must not be the same statement. Value-or-absent, as the
        # latency percentiles already are.
        if c.trials:
            lines.append(f"    observedPassRate: {c.observed_rate:.6f}")
        # Stated as an explicit null at zero trials: a consumer must be able
        # to tell "no evidence" from "field absent".
        bound = "null" if c.wilson_lower_bound is None else f"{c.wilson_lower_bound:.6f}"
        lines.append(f"    wilsonLowerBound: {bound}")
    if c.failure_distribution:
        # A sequence of entries, not a reason-keyed mapping: free-text keys
        # are what area rule 6 removed, and the axis needs a home beside the
        # condition rather than baked into a key.
        lines.append("    failureDistribution:")
        for reason in sorted(c.failure_distribution):
            entry: dict[str, object] = {
                "condition": bounded_excerpt(reason),
                "count": c.failure_distribution[reason],
            }
            axis = c.failure_axes.get(reason)
            if axis is not None:
                entry["reason"] = str(axis)
            lines.append("      - " + json.dumps(entry))
    if c.judgement is not None:
        lines.extend(
            [
                "    normativeJudgement:",
                f"      state: {quote(c.judgement.state)}",
                f"      stipulatedThreshold: {c.judgement.stipulated_threshold}",
                f"      confidence: {c.judgement.confidence}",
            ]
        )
    if c.optional_slack is not None:
        # The declared optional-check failure budget, verbatim as authored;
        # absent when undeclared — never "0". Additive in schema 2.
        lines.append(f"    optionalSlack: {quote(c.optional_slack)}")
    if c.standings:
        # Descriptive triage only — counts and the observed fraction; the
        # block never carries an interval, threshold, or per-check verdict.
        # Nested mappings (input index, then check), never a mapping list —
        # the reader's line parser takes list items as scalars only. Each
        # check states its optional flag beside the tallies (additive).
        lines.append("    postconditionStandings:")
        current_input: int | None = None
        for row in c.standings:
            if row.input_index != current_input:
                lines.append(f"      {quote(str(row.input_index))}:")
                current_input = row.input_index
            lines.extend(
                [
                    f"        {quote(bounded_key(row.postcondition))}:",
                    f"          optional: {'true' if row.optional else 'false'}",
                    f"          passed: {row.passed}",
                    f"          failed: {row.failed}",
                    f"          skipped: {row.skipped}",
                    f"          observedFraction: {row.observed_fraction:.6f}",
                ]
            )
            # Structured-row amendment: the check's stated structure and
            # obtained-value exemplars, additive in schema 2.
            if row.path is not None:
                lines.append(f"          path: {quote(bounded_excerpt(row.path))}")
            if row.form is not None:
                lines.append(f"          form: {quote(bounded_excerpt(row.form))}")
            if row.expected is not None:
                lines.append(f"          expected: {quote(bounded_excerpt(row.expected))}")
            if row.observed:
                # List items are scalars in this artefact's grammar (the
                # reader json-loads each line): one JSON object per exemplar.
                lines.append("          observed:")
                for exemplar in row.observed:
                    lines.append(
                        "            - "
                        + json.dumps(
                            {
                                "excerpt": exemplar.excerpt,
                                "count": exemplar.count,
                                "held": exemplar.held,
                            }
                        )
                    )
            if row.elided:
                lines.append(f"          elided: {row.elided}")
    return lines


def render_baseline(record: BaselineRecord) -> str:
    """Serialise a record to the artefact schema, deterministically."""
    lines = [
        f"schemaVersion: {quote(SCHEMA_VERSION)}",
        f"serviceContractId: {quote(record.service_contract_id)}",
        f"serviceName: {quote(record.service_name)}",
        f"generatedAt: {quote(record.generated_at.isoformat())}",
        f"confidenceLevel: {record.confidence_level}",
        f"inputsIdentity: {quote(record.inputs_identity)}",
    ]
    lines.append("covariateProfile:" if record.covariate_profile else "covariateProfile: {}")
    for key in sorted(record.covariate_profile):
        lines.append(f"  {quote(bounded_key(key))}: {quote(record.covariate_profile[key])}")
    if record.factor_record:
        lines.append("factorRecord:")
        for key in sorted(record.factor_record):
            lines.append(f"  {quote(bounded_key(key))}: {quote(record.factor_record[key])}")
    lines.extend(
        [
            "execution:",
            f"  samplesPlanned: {record.samples_planned}",
            f"  samplesExecuted: {record.samples_executed}",
            f"  terminationReason: {quote(record.termination_reason)}",
        ]
    )
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
    body = "\n".join(lines) + "\n"
    # The fingerprint covers the document with the fingerprint line absent,
    # which is exactly this body; a reader recomputes over the same text.
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"{FINGERPRINT_KEY}: {quote('sha256:' + digest)}\n"


def baseline_filename(record: BaselineRecord) -> str:
    """The artefact's canonical filename: the identity tuple, readably.

    Stable per identity: re-measuring the same pairing refreshes the
    artefact rather than accumulating copies. The name carries the service
    as well as the contract — a contract may exercise several services, and
    a name without the service segment collides between them (area rule 8).
    Filenames remain a human convenience: the body is authoritative, and a
    reader verifies the identity it loaded rather than trusting the path.
    """
    return baseline_filename_for(
        record.service_contract_id, record.service_name, record.inputs_identity
    )


def baseline_filename_for(contract_id: str, service_name: str, inputs_identity: str) -> str:
    """The filename the identity tuple resolves to. One grammar, one caller
    each side, so writer and reader cannot disagree about where a record
    lives."""
    return f"{_sanitise(contract_id)}.{_sanitise(service_name)}-{inputs_identity[:12]}.yaml"


def _sanitise(segment: str) -> str:
    """A filename segment: identifier characters only, bounded."""
    cleaned = "".join(c if (c.isalnum() or c in "_-") else "-" for c in segment)
    return cleaned[:64] or "unnamed"


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
