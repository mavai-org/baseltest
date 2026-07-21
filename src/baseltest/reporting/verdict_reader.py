"""Read-side of the verdict record: parsed rows for the HTML test report.

The renderer consumes persisted artefacts, never live run state — an inline
report (``--html-report``) and a post-hoc ``basel report test`` over the
same run parse the same XML and are identical by construction.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .run_design import BaselineDisclosure, ClaimDisclosure, RunDesign
from .verdict_xml import _NAMESPACE

# The Clark-notation namespace prefix ElementTree tags every parsed element
# with — derived from the writer's namespace so the two never drift apart.
_NS = f"{{{_NAMESPACE}}}"


@dataclass(frozen=True, slots=True)
class CriterionRow:
    """One per-criterion row as recorded."""

    criterion_id: str
    verdict: str
    passes: int
    fails: int
    total: int
    observed_rate: float
    threshold: float | None


@dataclass(frozen=True, slots=True)
class LatencyEvaluationRow:
    """One asserted latency bound's recorded evaluation."""

    percentile: str
    observed_ms: int | None
    threshold_ms: int
    provenance: str
    status: str
    baseline_confidence: float | None = None
    baseline_rank: int | None = None
    baseline_n: int | None = None


@dataclass(frozen=True, slots=True)
class LatencyRecord:
    """The verdict record's latency element, when present."""

    successful_samples: int
    observed: tuple[tuple[str, int], ...]
    evaluations: tuple[LatencyEvaluationRow, ...]

    def observed_ms(self, label: str) -> int | None:
        """The observed percentile for a label, or ``None`` when ungated."""
        for key, value in self.observed:
            if key == label:
                return value
        return None


@dataclass(frozen=True, slots=True)
class VerdictRecord:
    """One parsed verdict record — everything the test report renders."""

    contract_id: str
    verdict: str
    planned_samples: int
    successes: int
    failures: int
    elapsed_ms: int
    intent: str
    confidence: float
    criteria: tuple[CriterionRow, ...]
    clauses: tuple[tuple[str, int], ...] = ()
    latency: LatencyRecord | None = None
    origin: str = "UNSPECIFIED"
    contract_ref: str | None = None
    wilson_lower: float | None = None
    statistics_threshold: float | None = None
    design: RunDesign | None = None


def parse_verdict_record(text: str) -> VerdictRecord:
    """Parse one verdict-record document."""
    root = ElementTree.fromstring(text)
    execution = root.find(f"{_NS}execution")
    verdict = root.find(f"{_NS}verdict")
    assert execution is not None and verdict is not None

    criteria = []
    per_criterion = root.find(f"{_NS}per-criterion")
    if per_criterion is not None:
        for row in per_criterion.findall(f"{_NS}criterion"):
            threshold = row.get("threshold")
            criteria.append(
                CriterionRow(
                    criterion_id=row.get("id", ""),
                    verdict=row.get("verdict", ""),
                    passes=int(row.get("pass", "0")),
                    fails=int(row.get("fail", "0")),
                    total=int(row.get("total", "0")),
                    observed_rate=float(row.get("observed-rate", "0")),
                    threshold=float(threshold) if threshold is not None else None,
                )
            )

    clauses = []
    failures_element = root.find(f"{_NS}postcondition-failures")
    if failures_element is not None:
        clauses = [
            (clause.get("description", ""), int(clause.get("count", "0")))
            for clause in failures_element.findall(f"{_NS}clause")
        ]

    latency = None
    latency_element = root.find(f"{_NS}latency")
    if latency_element is not None:
        observed_element = latency_element.find(f"{_NS}observed")
        observed = tuple(
            (p.get("label", ""), int(p.get("value-ms", "0")))
            for p in (
                observed_element.findall(f"{_NS}percentile") if observed_element is not None else []
            )
        )
        evaluations = []
        evaluations_element = latency_element.find(f"{_NS}evaluations")
        for row in (
            evaluations_element.findall(f"{_NS}evaluation")
            if evaluations_element is not None
            else []
        ):
            observed_ms = row.get("observed-ms")
            baseline_confidence = row.get("baseline-confidence")
            baseline_rank = row.get("baseline-rank")
            baseline_n = row.get("baseline-n")
            evaluations.append(
                LatencyEvaluationRow(
                    percentile=row.get("percentile", ""),
                    observed_ms=int(observed_ms) if observed_ms is not None else None,
                    threshold_ms=int(row.get("threshold-ms", "0")),
                    provenance=row.get("provenance", "explicit"),
                    status=row.get("status", ""),
                    baseline_confidence=(
                        float(baseline_confidence) if baseline_confidence is not None else None
                    ),
                    baseline_rank=int(baseline_rank) if baseline_rank is not None else None,
                    baseline_n=int(baseline_n) if baseline_n is not None else None,
                )
            )
        latency = LatencyRecord(
            successful_samples=int(latency_element.get("successful-samples", "0")),
            observed=observed,
            evaluations=tuple(evaluations),
        )

    identity = root.find(f"{_NS}identity")
    provenance = root.find(f"{_NS}provenance")
    statistics = root.find(f"{_NS}statistics")
    design = _parse_design(root)
    wilson_lower = statistics.get("wilson-lower") if statistics is not None else None
    statistics_threshold = statistics.get("threshold") if statistics is not None else None
    return VerdictRecord(
        contract_id=identity.get("use-case-id", "") if identity is not None else "",
        verdict=verdict.get("value", "INCONCLUSIVE"),
        planned_samples=int(execution.get("planned-samples", "0")),
        successes=int(execution.get("successes", "0")),
        failures=int(execution.get("failures", "0")),
        elapsed_ms=int(execution.get("elapsed-ms", "0")),
        intent=execution.get("intent", ""),
        confidence=float(execution.get("confidence", "0.95")),
        criteria=tuple(criteria),
        clauses=tuple(clauses),
        latency=latency,
        origin=provenance.get("origin", "UNSPECIFIED") if provenance is not None else "UNSPECIFIED",
        contract_ref=provenance.get("contract-ref") if provenance is not None else None,
        wilson_lower=float(wilson_lower) if wilson_lower is not None else None,
        statistics_threshold=(
            float(statistics_threshold) if statistics_threshold is not None else None
        ),
        design=design,
    )


def _parse_design(root: ElementTree.Element) -> RunDesign | None:
    """The recorded run design: environment sizing entries plus the
    ``baseline`` element. Records that predate the disclosures parse to
    ``None`` and render without a design block."""
    environment = root.find(f"{_NS}environment")
    entries: dict[str, str] = {}
    if environment is not None:
        for element in environment.findall(f"{_NS}entry"):
            entries[element.get("key", "")] = element.get("value", "")
    approach = entries.get("sizing-approach")
    if approach is None:
        return None

    claims = []
    for key, value in entries.items():
        if not key.startswith("sizing-claim:"):
            continue
        body = json.loads(value)
        claims.append(
            ClaimDisclosure(
                criterion=key.removeprefix("sizing-claim:"),
                baseline_rate=float(body["baselineRate"]),
                tolerated_rate=float(body["toleratedRate"]),
                confidence=float(body["confidence"]),
                target_power=float(body["targetPower"]),
                required_n=int(body["requiredN"]) if body.get("requiredN") is not None else None,
            )
        )

    baseline_element = root.find(f"{_NS}baseline")
    baseline = None
    if baseline_element is not None:
        baseline = BaselineDisclosure(
            source_file=baseline_element.get("source-file", ""),
            generated_at=baseline_element.get("generated-at", ""),
            samples=int(baseline_element.get("samples", "0")),
            baseline_rate=float(baseline_element.get("baseline-rate", "0")),
            derived_threshold=float(baseline_element.get("derived-threshold", "0")),
        )

    return RunDesign(
        approach=approach,
        claims=tuple(sorted(claims, key=lambda c: c.criterion)),
        governing=entries.get("sizing-governing"),
        baseline=baseline,
    )


@dataclass(frozen=True, slots=True)
class VerdictSweep:
    """Every parseable verdict record under a directory, with skip notes."""

    records: tuple[VerdictRecord, ...]
    skipped: tuple[str, ...] = field(default=())


def read_verdict_directory(directory: Path) -> VerdictSweep:
    """Parse every ``*.xml`` under ``directory``; unparseable files are
    skipped by name, never silently."""
    records = []
    skipped = []
    for path in sorted(directory.glob("*.xml")):
        try:
            records.append(parse_verdict_record(path.read_text(encoding="utf-8")))
        except (ElementTree.ParseError, ValueError, AssertionError):
            skipped.append(path.name)
    return VerdictSweep(records=tuple(records), skipped=tuple(skipped))
