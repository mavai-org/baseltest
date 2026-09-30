"""The canonical verdict record: the family's test-results schema, emitted.

Test runs emit their results in the mavai family's verdict XML
(``verdict-1.7.xsd``, namespace ``http://mavai.org/verdict/1.0``) — so
every framework's results are readable by the same tooling. baseltest
emits the subset it has data for; every emitted element conforms.
``version="1.7"`` names the decision behind the verdict: the methodology
version on the record, the versioned decision rule on every criterion row
and strict latency evaluation (and on the verdict when one rule decided the
whole test), the smallest passing count on every criterion row (when any
count can pass), the latency dimension's verdict, and — for a
configuration refused before any sample ran — the configuration-error list
and no verdict value. The verdict's value is the test's verdict
``V_test``, the structural composite of the functional and latency
dimensions. The run's failure attribution travels in the ``functional``
element, one ``check`` per bounded identity with the kind that says
whether those trials were judged or never delivered anything to judge.
The per-criterion decomposition is always populated, and the descriptive
postcondition standings travel in the first-class
``postcondition-standings`` element — counts, the observed fraction, the
per-row optional flag, and the declared slack verbatim; never an interval
or a per-check verdict. The transitional environment-entry carriage some
1.2 emissions used is gone: a 1.3 record states standings once.
"""

import json
from pathlib import Path
from xml.etree import ElementTree

from baseltest._version import __version__
from baseltest.contract import ServiceContract
from baseltest.engine import (
    METHODOLOGY_VERSION,
    BoundEvaluation,
    ConfigurationRefusedError,
    CriterionResult,
    RegressionVerdict,
    RunPlan,
    RunResult,
    Verdict,
)
from baseltest.engine.naming import bounded_excerpt, bounded_key

from .run_design import RunDesign

_NAMESPACE = "http://mavai.org/verdict/1.0"
_FORMAT_VERSION = "1.7"

# The run-design facts ride the schema's free-form environment entries —
# the family verdict schema itself is unchanged by the sizing disclosures.
SIZING_APPROACH_KEY = "sizing-approach"
SIZING_GOVERNING_KEY = "sizing-governing"
SIZING_CLAIM_PREFIX = "sizing-claim:"


def _generator() -> str:
    return f"baseltest {__version__}"


def _origin(result: CriterionResult) -> str:
    return result.criterion.provenance.origin.upper()


def _threshold(result: CriterionResult) -> str:
    """The row's threshold: a requirement as declared, a cutoff as ``c / n_t``."""
    decision = result.decision
    assert decision is not None
    if isinstance(decision, RegressionVerdict):
        return str(decision.derivation.threshold_real)
    return str(decision.requirement)


def _required_pass(result: CriterionResult) -> int | None:
    """The smallest count that passes under the row's rule: PASS iff it is reached.

    The Fisher cutoff under ``regression/fisher``, ``k_min`` under
    ``compliance/exact-binomial`` -- the count the engine judged with, never
    one recovered from the threshold. ``None`` when no count can pass.
    """
    decision = result.decision
    assert decision is not None
    if isinstance(decision, RegressionVerdict):
        return decision.cutoff
    return decision.minimum_passing


# The verdict record's evaluation status for a strict constraint's verdict.
_STRICT_STATUS = {
    Verdict.PASS: "PASS",
    Verdict.FAIL: "STRICT_FAIL",
    Verdict.INCONCLUSIVE: "INFEASIBLE",
}


def _root(timestamp: str) -> ElementTree.Element:
    ElementTree.register_namespace("", _NAMESPACE)
    root = ElementTree.Element(f"{{{_NAMESPACE}}}verdict-record")
    root.set("version", _FORMAT_VERSION)
    root.set("methodology-version", METHODOLOGY_VERSION)
    root.set("timestamp", timestamp)
    root.set("generator", _generator())
    return root


def _child(parent: ElementTree.Element, name: str) -> ElementTree.Element:
    return ElementTree.SubElement(parent, f"{{{_NAMESPACE}}}{name}")


def _document(root: ElementTree.Element) -> str:
    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def _evaluation(parent: ElementTree.Element, outcome: BoundEvaluation, confidence: float) -> None:
    """One strict latency evaluation, with the rule that decided it.

    A saturated baseline-derived constraint — no baseline rank achieves
    alpha for the test's count — is recorded as ``SATURATED`` with no
    ``threshold-ms`` and no ``baseline-rank``: there is no threshold, and
    none is manufactured. A baseline-derived constraint with no successful
    latency at all has no rank search to report, and no row; its
    INCONCLUSIVE outcome is carried by the latency element's verdict.
    """
    judgement = outcome.judgement
    precedence = judgement.precedence
    saturated = precedence is not None and precedence.saturated
    threshold = judgement.threshold_ms
    if threshold is None and not saturated:
        return
    row = _child(parent, "evaluation")
    row.set("percentile", outcome.bound.percentile)
    if judgement.observed_ms is not None:
        row.set("observed-ms", str(round(judgement.observed_ms)))
    if threshold is not None:
        row.set("threshold-ms", str(round(threshold)))
    row.set("provenance", str(judgement.source))
    row.set("mode", "strict")
    row.set("status", "SATURATED" if saturated else _STRICT_STATUS[outcome.verdict])
    if precedence is not None:
        row.set("baseline-confidence", str(confidence))
        if precedence.rank is not None:
            row.set("baseline-rank", str(precedence.rank))
        row.set("baseline-n", str(precedence.n))
    rule = judgement.rule
    assert rule is not None
    row.set("decision-rule", rule.value)
    row.set("decision-rule-version", str(rule.version))
    compliance = judgement.compliance
    if compliance is not None:
        row.set("within-threshold", str(compliance.within_threshold))
        if compliance.minimum_within is not None:
            row.set("required-within", str(compliance.minimum_within))


def render_verdict_record(result: RunResult, design: RunDesign | None = None) -> str:
    """Render a completed test run as one ``verdict-record`` document.

    ``design`` — when the caller recorded how the run's size came about —
    is carried inside the family schema: the resolved baseline in the
    schema's ``baseline`` element, the approach and any risk-driven claims
    as ``environment`` entries."""
    root = _root(result.finished_at.isoformat())
    child = _child

    identity = child(root, "identity")
    identity.set("use-case-id", result.contract_id)

    judged = [r for r in result.criterion_results if r.decision is not None]
    confidence = judged[0].criterion.confidence if judged else _latency_confidence(result)
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
        strict_violations = sum(1 for e in result.latency.evaluations if e.verdict is Verdict.FAIL)
        latency.set("strict-violations", str(strict_violations))
        latency.set("advisory-violations", "0")  # declaring the bar is the opt-in; no advisory mode
        latency.set("verdict", result.latency.verdict.value.upper())
        observed = child(latency, "observed")
        for label, value_ms in result.latency.observed:
            percentile = child(observed, "percentile")
            percentile.set("label", label)
            percentile.set("value-ms", str(value_ms))
        evaluations = child(latency, "evaluations")
        for evaluation in result.latency.evaluations:
            _evaluation(evaluations, evaluation, result.latency.bar.confidence)

    if len(judged) == 1:
        only = judged[0]
        assert only.lower_bound is not None
        statistics = child(root, "statistics")
        statistics.set("confidence-level", str(only.criterion.confidence))
        statistics.set("standard-error", str(only.tally.standard_error))
        statistics.set("wilson-lower", str(only.lower_bound))
        statistics.set("threshold", _threshold(only))
        statistics.set("threshold-origin", _origin(only))
        if isinstance(only.decision, RegressionVerdict):
            size = only.decision.derivation.size_at_assumed_common_rate
            if size is not None:
                statistics.set("size-at-assumed-common-rate", str(size))
            power = only.power
            if power is not None and power.design_alternative_rate is not None:
                statistics.set("design-alternative-rate", str(power.design_alternative_rate))
                statistics.set("design-power", str(power.design_power))
                statistics.set("resolved-test-power", str(power.resolved_power))

    covariates = child(root, "covariates")
    covariates.set("aligned", "true")  # a mismatched baseline never judges (skip w/ reason)

    # How each input the run drove presents itself (1.6). Every input is
    # named, not only the ones a failure came from: a report naming the
    # rows that misbehaved and leaving the rest blank names some rows and
    # not others. The excerpt is for orientation and is never identity —
    # that stays the inputs fingerprint.
    if result.plan.inputs:
        inputs = child(root, "inputs")
        for index, value in enumerate(result.plan.inputs):
            presentation = child(inputs, "input")
            presentation.set("index", str(index))
            presentation.set("excerpt", bounded_excerpt(str(value)))

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
                        "designAlternativeRate": claim.design_alternative_rate,
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

    overall = result.overall
    assert overall is not None
    if judged:
        per_criterion = child(root, "per-criterion")
        for criterion_result in judged:
            decision = criterion_result.decision
            assert decision is not None
            row = child(per_criterion, "criterion")
            row.set("id", criterion_result.name)
            row.set("verdict", decision.verdict.value.upper())
            row.set("pass", str(criterion_result.tally.successes))
            row.set("fail", str(criterion_result.tally.trials - criterion_result.tally.successes))
            row.set("inconclusive", "0")
            row.set("total", str(criterion_result.tally.trials))
            row.set("observed-rate", str(criterion_result.tally.observed_rate))
            row.set("threshold", _threshold(criterion_result))
            row.set("decision-rule", decision.rule.value)
            row.set("decision-rule-version", str(decision.rule.version))
            required_pass = _required_pass(criterion_result)
            if required_pass is not None:
                row.set("required-pass", str(required_pass))
        composite = child(per_criterion, "composite")
        assert overall.rate_verdict is not None
        composite.set("value", overall.rate_verdict.value.upper())

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
                row.set("provenance", standing.provenance)
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
    verdict.set("value", overall.verdict.value.upper())
    rules = {r.decision.rule for r in judged if r.decision is not None}
    if result.latency is not None:
        rules.update(e.judgement.rule for e in result.latency.evaluations if e.judgement.rule)
    if len(rules) == 1:
        (rule,) = rules
        verdict.set("decision-rule", rule.value)
        verdict.set("decision-rule-version", str(rule.version))
    return _document(root)


def _latency_confidence(result: RunResult) -> float:
    """The execution confidence of a test with no functional bar: its latency bar's."""
    assert result.latency is not None
    return result.latency.bar.confidence


def write_verdict_record(
    result: RunResult, directory: Path, design: RunDesign | None = None
) -> Path:
    """Write the record to ``<directory>/<contract>-<inputs tail>.xml``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.contract_id}-{result.inputs_identity[:12]}.xml"
    path.write_text(render_verdict_record(result, design), encoding="utf-8")
    return path


def render_refused_record(
    contract: ServiceContract[object],
    plan: RunPlan,
    refused: ConfigurationRefusedError,
    timestamp: str,
) -> str:
    """Render a configuration refused before any sample ran.

    The record states every applicable code, in the fixed order, and no
    verdict value — there is no verdict, and a refusal is not INCONCLUSIVE —
    with the termination reason ``CONFIGURATION_REFUSED``.
    """
    root = _root(timestamp)
    identity = _child(root, "identity")
    identity.set("use-case-id", contract.contract_id)
    confidences = [c.confidence for c in contract.criteria if c.is_judged]
    if not confidences and contract.latency is not None:
        confidences.append(contract.latency.confidence)
    execution = _child(root, "execution")
    execution.set("planned-samples", str(plan.samples))
    execution.set("samples-executed", "0")
    execution.set("successes", "0")
    execution.set("failures", "0")
    execution.set("elapsed-ms", "0")
    execution.set("intent", plan.intent.name)
    execution.set("confidence", str(confidences[0] if confidences else 0.95))
    covariates = _child(root, "covariates")
    covariates.set("aligned", "true")
    termination = _child(root, "termination")
    termination.set("reason", "CONFIGURATION_REFUSED")
    termination.set("detail", "; ".join(f"{p.code}: {p.subject}" for p in refused.parts))
    verdict = _child(root, "verdict")
    verdict.set("configuration-error", " ".join(refused.errors))
    return _document(root)


def write_refused_record(
    contract: ServiceContract[object],
    plan: RunPlan,
    inputs_identity: str,
    refused: ConfigurationRefusedError,
    directory: Path,
    timestamp: str,
) -> Path:
    """Write a refused configuration's record beside the run records."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{contract.contract_id}-{inputs_identity[:12]}.xml"
    path.write_text(render_refused_record(contract, plan, refused, timestamp), encoding="utf-8")
    return path
