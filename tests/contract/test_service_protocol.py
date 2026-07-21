"""The service seam is a structural ``Service`` protocol, not a bare callable.

Because ``Service`` matches by shape (``(request) -> str``), an author may hand
over anything of that shape — a function, a lambda, or a stateful callable
object — without inheriting from anything. This pins the callable-object case,
which a narrower ``Callable`` annotation would still accept but which the
protocol is what makes intentional.
"""

from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.engine import RunKind, RunPlan, Verdict, execute


class StubService:
    """A stateful callable object standing in for a real service client."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls = 0

    def __call__(self, request: str) -> str:
        self.calls += 1
        return f"{self._reply} for {request}"


def test_callable_object_is_a_service() -> None:
    service = StubService("ok")
    contract: ServiceContract[str] = ServiceContract(
        contract_id="callable-object",
        invoke=service,
        criteria=(Criterion(name="relevant", postconditions=(contains("ok"),), threshold=0.5),),
    )
    result = execute(contract, RunPlan(samples=20, inputs=("a", "b"), kind=RunKind.TEST))
    assert result.composite is Verdict.PASS
    assert service.calls == 20
