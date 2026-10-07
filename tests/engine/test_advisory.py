"""Advisory dimensions: decided by their rules and reported, never failing the test."""

import time
from itertools import count

import pytest

from baseltest.contract import Criterion, LatencyBar, LatencyBound, ServiceContract, contains
from baseltest.engine import (
    ConfigurationError,
    ConfigurationRefusedError,
    Dimension,
    EnforcementMode,
    RunPlan,
    RunResult,
    Verdict,
    execute,
)

FUNCTIONAL = frozenset({Dimension.FUNCTIONAL})
LATENCY = frozenset({Dimension.LATENCY})
BOTH = FUNCTIONAL | LATENCY


def slow_service(fail_every: int = 0) -> object:
    """A service slower than a 1 ms requirement, failing every `fail_every`-th call."""
    counter = count(1)

    def invoke(_input: str) -> str:
        time.sleep(0.002)
        n = next(counter)
        return "bad" if fail_every and n % fail_every == 0 else "ok"

    return invoke


def contract(threshold: float, fail_every: int = 0) -> ServiceContract:
    # Every latency exceeds the p50 <= 1 ms requirement: the latency
    # dimension FAILs by latency/compliance-exact-binomial.
    return ServiceContract(
        contract_id="svc",
        invoke=slow_service(fail_every),  # type: ignore[arg-type]
        criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=threshold),),
        latency=LatencyBar(bounds=(LatencyBound("p50", 1),)),
    )


def run(
    service_contract: ServiceContract, advisory: frozenset[Dimension] = frozenset()
) -> RunResult:
    return execute(service_contract, RunPlan(samples=10, inputs=("a",), advisory=advisory))


def test_every_dimension_is_enforced_by_default() -> None:
    result = run(contract(0.5))
    assert result.overall is not None
    assert result.overall.functional_mode is EnforcementMode.ENFORCED
    assert result.overall.latency_mode is EnforcementMode.ENFORCED
    assert result.composite is Verdict.FAIL
    assert [t.id for t in result.overall.triggering] == ["latency p50"]


def test_advisory_latency_is_decided_and_reported_but_does_not_fail_the_test() -> None:
    result = run(contract(0.5), LATENCY)
    assert result.overall is not None
    assert result.latency is not None and result.latency.verdict is Verdict.FAIL
    assert result.overall.latency_verdict is Verdict.FAIL
    assert result.overall.latency_mode is EnforcementMode.ADVISORY
    assert result.composite is Verdict.PASS
    # The advisory requirement makes no binding decision: only the
    # functional requirement's alpha enters the false-compliance envelope.
    assert result.envelopes.false_compliance == pytest.approx(0.05)


def test_advisory_functional_leaves_the_latency_dimension_to_decide() -> None:
    result = run(contract(0.6, fail_every=2), FUNCTIONAL)
    assert result.overall is not None
    assert result.overall.rate_verdict is Verdict.FAIL
    assert result.overall.functional_mode is EnforcementMode.ADVISORY
    assert result.composite is Verdict.FAIL
    assert [t.id for t in result.overall.triggering] == ["latency p50"]


def test_with_both_advisory_the_test_cannot_fail_on_its_assertions() -> None:
    result = run(contract(0.6, fail_every=2), BOTH)
    assert result.overall is not None
    assert (result.overall.rate_verdict, result.overall.latency_verdict) == (
        Verdict.FAIL,
        Verdict.FAIL,
    )
    assert result.composite is Verdict.PASS
    assert result.overall.triggering == ()
    assert result.envelopes.false_compliance is None
    assert result.envelopes.false_degradation_signal is None


def test_an_advisory_dimension_is_still_refused_when_no_outcome_could_decide_it() -> None:
    # 10 samples cannot demonstrate a 0.99 requirement, enforced or advisory.
    with pytest.raises(ConfigurationRefusedError) as refused:
        run(contract(0.99), BOTH)
    assert refused.value.errors == (ConfigurationError.COMPLIANCE_INFEASIBLE,)
