"""The canonical verdict record: the family's test-results schema, emitted.

Test runs emit their results in the mavai family's verdict XML — the
schema punit defines (``verdict-1.2.xsd``, namespace
``http://mavai.org/verdict/1.0``) — so every framework's results are
readable by the same tooling. baseltest emits the subset it has data for;
every emitted element conforms. ``version="1.2"``: the per-criterion
decomposition is always populated.
"""

import math
from importlib import metadata
from pathlib import Path
from xml.etree import ElementTree

from baseltest.engine import CriterionResult, RunResult

_NAMESPACE = "http://mavai.org/verdict/1.0"


def _generator() -> str:
    try:
        return f"baseltest {metadata.version('baseltest')}"
    except metadata.PackageNotFoundError:  # editable/dev edge
        return "baseltest"


def _standard_error(successes: int, trials: int) -> float:
    if trials == 0:
        return 0.0
    rate = successes / trials
    return math.sqrt(rate * (1 - rate) / trials)


def _origin(result: CriterionResult) -> str:
    return result.criterion.provenance.origin.upper()


def render_verdict_record(result: RunResult) -> str:
    """Render a completed test run as one ``verdict-record`` document."""
    ElementTree.register_namespace("", _NAMESPACE)
    root = ElementTree.Element(f"{{{_NAMESPACE}}}verdict-record")
    root.set("version", "1.2")
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

    if len(judged) == 1:
        only = judged[0]
        assert only.lower_bound is not None and only.criterion.threshold is not None
        statistics = child(root, "statistics")
        statistics.set("confidence-level", str(only.criterion.confidence))
        statistics.set(
            "standard-error", str(_standard_error(only.tally.successes, only.tally.trials))
        )
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

    termination = child(root, "termination")
    termination.set("reason", "COMPLETED")

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

    verdict = child(root, "verdict")
    verdict.set("value", result.composite.value.upper())

    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def write_verdict_record(result: RunResult, directory: Path) -> Path:
    """Write the record to ``<directory>/<contract>-<inputs tail>.xml``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.contract_id}-{result.inputs_identity[:12]}.xml"
    path.write_text(render_verdict_record(result), encoding="utf-8")
    return path
