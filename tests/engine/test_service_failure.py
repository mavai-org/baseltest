"""Failed delivery: an unreachable service is a failed service, judged as such."""

import itertools

from baseltest.contract import Criterion, ServiceContract, ServiceDeliveryError, contains
from baseltest.engine import RunKind, RunPlan, Verdict, execute


def flaky_delivery(fail_every: int = 2):  # type: ignore[no-untyped-def]
    counter = itertools.count()

    def invoke(value: str) -> str:
        if next(counter) % fail_every == 1:
            raise ServiceDeliveryError("service unreachable at https://api.example: refused")
        return "ok"

    return invoke


class TestFailedDelivery:
    def test_counts_against_every_criterion_with_the_cause(self) -> None:
        contract = ServiceContract(
            contract_id="svc",
            invoke=flaky_delivery(),
            criteria=(
                Criterion(name="a", postconditions=(contains("ok"),), threshold=0.2),
                Criterion(name="b", postconditions=(contains("ok"),)),
            ),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("x",), kind=RunKind.TEST))
        for criterion_result in result.criterion_results:
            assert criterion_result.tally.trials == 10
            assert criterion_result.tally.successes == 5
            reasons = dict(criterion_result.tally.failure_reasons)
            assert reasons == {"service unreachable at https://api.example: refused": 5}
        assert result.overall_successes == 5
        # The verdict judges the Wilson lower bound (~0.24 at 5/10), which
        # clears the 0.2 bar: failed deliveries count, without being fatal.
        assert result.composite is Verdict.PASS

    def test_total_outage_renders_a_fail_verdict_not_an_abort(self) -> None:
        def dead(value: str) -> str:
            raise ServiceDeliveryError("service unreachable at https://api.example: no DNS")

        contract = ServiceContract(
            contract_id="svc",
            invoke=dead,
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("x",), kind=RunKind.TEST))
        assert result.composite is Verdict.FAIL
        assert result.criterion_results[0].tally.successes == 0

    def test_undelivered_samples_contribute_no_latency(self) -> None:
        from baseltest.contract import LatencyBar, LatencyBound

        contract = ServiceContract(
            contract_id="svc",
            invoke=flaky_delivery(),
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.4),),
            latency=LatencyBar(bounds=(LatencyBound("p50", 60_000),)),
        )
        result = execute(contract, RunPlan(samples=10, inputs=("x",), kind=RunKind.TEST))
        assert result.latency is not None
        assert result.latency.contributing_samples == 5

    def test_recorded_samples_carry_skipped_postconditions_and_no_content(self) -> None:
        contract = ServiceContract(
            contract_id="svc",
            invoke=flaky_delivery(),
            criteria=(Criterion(name="c", postconditions=(contains("ok"),)),),
        )
        result = execute(
            contract,
            RunPlan(samples=4, inputs=("x",), kind=RunKind.EXPLORE),
            record_samples=True,
        )
        failed = [s for s in result.samples if not s.passed]
        assert failed and all(s.content == "" for s in failed)
        assert all(status == "skipped" for s in failed for _, status in s.postconditions)

    def test_other_exceptions_remain_defects_and_abort(self) -> None:
        import pytest

        def buggy(value: str) -> str:
            raise RuntimeError("a genuine bug")

        contract = ServiceContract(
            contract_id="svc",
            invoke=buggy,
            criteria=(Criterion(name="c", postconditions=(contains("ok"),), threshold=0.5),),
        )
        with pytest.raises(RuntimeError):
            execute(contract, RunPlan(samples=3, inputs=("x",), kind=RunKind.TEST))
