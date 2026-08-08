"""The canonical verdict record: the family's test-results schema, emitted.

Test runs emit their results in the mavai family's verdict XML
(``verdict-1.5.xsd``, namespace ``http://mavai.org/verdict/1.0``) — so
every framework's results are readable by the same tooling. baseltest
emits the subset it has data for; every emitted element conforms.
``version="1.5"``: the run's failure attribution travels in the
``functional`` element, one ``check`` per bounded identity with the kind
that says whether those trials were judged or never delivered anything to
judge. The per-criterion decomposition is always populated, and the
descriptive postcondition standings travel in the first-class
``postcondition-standings`` element — counts, the observed fraction, the
per-row optional flag, and the declared slack verbatim; never an interval
or a per-check verdict. The transitional environment-entry carriage some
1.2 emissions used is gone: a 1.3 record states standings once.
"""

import json
from pathlib import Path
from xml.etree import ElementTree

from baseltest._version import __version__
from baseltest.engine import CriterionResult, RunResult
from baseltest.engine.naming import bounded_excerpt, bounded_key

from .run_design import RunDesign

_NAMESPACE = "http://mavai.org/verdict/1.0"
_FORMAT_VERSION = "1.5"

# The run-design facts ride the schema's free-form environment entries —
# the family verdict schema itself is unchanged by the sizing disclosures.
SIZING_APPROACH_KEY = "sizing-approach"
SIZING_GOVERNING_KEY = "sizing-governing"
SIZING_CLAIM_PREFIX = "sizing-claim:"


def _generator() -> str:
    return f"baseltest {__version__}"


def _origin(result: CriterionResult) -> str:
    return result.criterion.provenance.origin.upper()


def render_verdict_record(result: RunResult, design: RunDesign | None = None) -> str:
    """Render a completed test run as one ``verdict-record`` document.

    ``design`` — when the caller recorded how the run's size came about —
    is carried inside the family schema: the resolved baseline in the
    schema's ``baseline`` element, the approach and any risk-driven claims
    as ``environment`` entries."""
    ElementTree.register_namespace("", _NAMESPACE)
    root = ElementTree.Element(f"{{{_NAMESPACE}}}verdict-record")
    root.set("version", _FORMAT_VERSION)
    root.set("timestamp", result.finished_at.isoformat())
    root.set("generator", _generator())

    def child(parent: ElementTree.Element, name: str) -> ElementTree.Element:
        return ElementTree.SubElement(parent, f"{{{_NAMESPACE}}}{name}")

    identity = child(root, "identity")
    identity.set("use-case-id", result.contract_id)

    judged = list(result.criterion_results)
    confidence = judged[0].criterion.confidence if judged else 0.95
    execution = child(root, "execution")
    execution.set("planned-samples", str(result.plan.samples))
    execution.set("samples-executed", str(result.plan.samples))
    execution.set("successes", str(result.overall_successes))
    execution.set("failures", str(result.plan.samples - result.overall_successes))
    elapsed = int((result.finished_at - result.started_at).total_seconds() * 1000)
    execution.set("elapsed-ms", str(elapsed))
    execution.set("intent", result.plan.intent.name)
    execution.set("confidence", str(confidence))

    if result.latency is not None:
        latency = child(root, "latency")
        latency.set("successful-samples", str(result.latency.contributing_samples))
        strict_violations = sum(1 for e in result.latency.evaluations if e.status == "fail")
        latency.set("strict-violations", str(strict_violations))
        latency.set("advisory-violations", "0")  # declaring the bar is the opt-in; no advisory mode
        observed = child(latency, "observed")
        for label, value_ms in result.latency.observed:
            percentile = child(observed, "percentile")
            percentile.set("label", label)
            percentile.set("value-ms", str(value_ms))
        evaluations = child(latency, "evaluations")
        for evaluation in result.latency.evaluations:
            row = child(evaluations, "evaluation")
            row.set("percentile", evaluation.bound.percentile)
            if evaluation.observed_ms is not None:
                row.set("observed-ms", str(evaluation.observed_ms))
            row.set("threshold-ms", str(evaluation.bound.threshold_ms))
            row.set("provenance", result.latency.bar.origin)
            row.set("mode", "strict")
            status = {"pass": "PASS", "fail": "STRICT_FAIL", "infeasible": "INFEASIBLE"}
            row.set("status", status[evaluation.status])
            if result.latency.bar.origin == "baseline-derived":
                row.set("baseline-confidence", str(result.latency.bar.confidence))
                if evaluation.bound.rank is not None:
                    row.set("baseline-rank", str(evaluation.bound.rank))
                if evaluation.bound.baseline_samples is not None:
                    row.set("baseline-n", str(evaluation.bound.baseline_samples))

    if len(judged) == 1:
        only = judged[0]
        assert only.lower_bound is not None and only.criterion.threshold is not None
        statistics = child(root, "statistics")
        statistics.set("confidence-level", str(only.criterion.confidence))
        statistics.set("standard-error", str(only.tally.standard_error))
        statistics.set("wilson-lower", str(only.lower_bound))
        statistics.set("threshold", str(only.criterion.threshold))
        statistics.set("threshold-origin", _origin(only))

    covariates = child(root, "covariates")
    covariates.set("aligned", "true")  # a mismatched baseline never judges (skip w/ reason)

    origins = {_origin(r) for r in judged}
    provenance = child(root, "provenance")
    provenance.set("origin", origins.pop() if len(origins) == 1 else "UNSPECIFIED")
    refs = [
        r.criterion.provenance.contract_ref
        for r in judged
        if r.criterion.provenance.contract_ref is not None
    ]
    if refs:
        provenance.set("contract-ref", refs[0])

    # A baseline element needs its full identity; a record missing the
    # measurement timestamp (a pre-timestamp artefact) is not emitted.
    if design is not None and design.baseline is not None and design.baseline.generated_at:
        stored = design.baseline
        baseline = child(root, "baseline")
        baseline.set("source-file", stored.source_file)
        baseline.set("generated-at", stored.generated_at)
        baseline.set("samples", str(stored.samples))
        baseline.set("baseline-rate", str(stored.baseline_rate))
        baseline.set("derived-threshold", str(stored.derived_threshold))

    termination = child(root, "termination")
    termination.set("reason", "COMPLETED")

    if design is not None:
        environment = child(root, "environment")

        def entry(key: str, value: str) -> None:
            element = child(environment, "entry")
            element.set("key", key)
            element.set("value", value)

        entry(SIZING_APPROACH_KEY, design.approach)
        if design.governing is not None:
            entry(SIZING_GOVERNING_KEY, design.governing)
        for claim in design.claims:
            entry(
                f"{SIZING_CLAIM_PREFIX}{claim.criterion}",
                json.dumps(
                    {
                        "baselineRate": claim.baseline_rate,
                        "toleratedRate": claim.tolerated_rate,
                        "confidence": claim.confidence,
                        "targetPower": claim.target_power,
                        "requiredN": claim.required_n,
                    }
                ),
            )

    # The run's failure attribution: per trial, each counted once against
    # the first thing that failed it, with the bounded identity and the
    # kind. This is what lets a consumer tell a run that measured nothing
    # from a run that measured everything and found it wanting — the two
    # states this record used to spell identically.
    functional = child(root, "functional")
    functional.set("successes", str(result.overall_successes))
    functional.set("failures", str(result.plan.samples - result.overall_successes))
    functional.set("pass-rate", str(result.observed_rate))
    if result.failure_attribution:
        distribution = child(functional, "failure-distribution")
        for attribution in result.failure_attribution:
            check = child(distribution, "check")
            check.set("name", attribution.condition)
            check.set("count", str(attribution.count))
            check.set("kind", str(attribution.kind))

    reasons: dict[str, int] = {}
    for criterion_result in judged:
        for reason, count in criterion_result.tally.failure_reasons.items():
            reasons[reason] = reasons.get(reason, 0) + count
    if reasons:
        failures = child(root, "postcondition-failures")
        for reason in sorted(reasons):
            clause = child(failures, "clause")
            clause.set("description", reason)
            clause.set("count", str(reasons[reason]))

    per_criterion = child(root, "per-criterion")
    for criterion_result in judged:
        assert criterion_result.verdict is not None
        row = child(per_criterion, "criterion")
        row.set("id", criterion_result.name)
        row.set("verdict", criterion_result.verdict.value.upper())
        row.set("pass", str(criterion_result.tally.successes))
        row.set("fail", str(criterion_result.tally.trials - criterion_result.tally.successes))
        row.set("inconclusive", "0")
        row.set("total", str(criterion_result.tally.trials))
        row.set("observed-rate", str(criterion_result.tally.observed_rate))
        if criterion_result.criterion.threshold is not None:
            row.set("threshold", str(criterion_result.criterion.threshold))
    composite = child(per_criterion, "composite")
    assert result.composite is not None
    composite.set("value", result.composite.value.upper())

    # The first-class standings element (1.3): descriptive tallies only,
    # the optional flag on every row, the declared slack verbatim and only
    # when declared — absence is distinguishable from "0".
    with_standings = [r for r in judged if r.standings]
    if with_standings:
        standings_element = child(root, "postcondition-standings")
        for criterion_result in with_standings:
            block = child(standings_element, "criterion")
            block.set("name", criterion_result.name)
            slack = criterion_result.criterion.optional_slack
            if slack is not None:
                block.set("optional-slack", slack.declared)
            for standing in criterion_result.standings:
                row = child(block, "row")
                row.set("input-index", str(standing.input_index))
                row.set("check", bounded_key(standing.postcondition))
                row.set("optional", "true" if standing.optional else "false")
                row.set("passed", str(standing.passed))
                row.set("failed", str(standing.failed))
                row.set("skipped", str(standing.skipped))
                row.set("observed-fraction", str(standing.observed_fraction))
                # The check's stated structure and obtained-value exemplars
                # (structured-row amendment): content in values only.
                if standing.path is not None:
                    row.set("path", bounded_excerpt(standing.path))
                if standing.form is not None:
                    row.set("form", bounded_excerpt(standing.form))
                if standing.expected is not None:
                    row.set("expected", bounded_excerpt(standing.expected))
                if standing.elided:
                    row.set("elided", str(standing.elided))
                for exemplar in standing.observed:
                    observed = child(row, "observed")
                    observed.set("excerpt", exemplar.excerpt)
                    observed.set("count", str(exemplar.count))
                    observed.set("held", "true" if exemplar.held else "false")

    verdict = child(root, "verdict")
    verdict.set("value", result.composite.value.upper())

    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def write_verdict_record(
    result: RunResult, directory: Path, design: RunDesign | None = None
) -> Path:
    """Write the record to ``<directory>/<contract>-<inputs tail>.xml``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.contract_id}-{result.inputs_identity[:12]}.xml"
    path.write_text(render_verdict_record(result, design), encoding="utf-8")
    return path
