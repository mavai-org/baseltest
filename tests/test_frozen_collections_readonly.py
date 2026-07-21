"""Collection fields on frozen records are read-only and caller-isolated.

A ``@dataclass(frozen=True)`` stops *reassignment* of a field but not *in-place
mutation* of a dict it holds — and such a dict, shared with the caller who
passed it, is a mutable back door into a value object. Each record wraps these
fields in a ``MappingProxyType`` over a private copy in ``__post_init__``, so
mutation raises and the caller's later edits cannot leak in. The mechanism is
uniform; ``ServiceTypeContract.covariates`` (10 callable fields, awkward to
build here) follows the same wrapping.
"""

from datetime import UTC, datetime

import pytest

from baseltest.baseline import BaselineRecord, CriterionCharacterisation
from baseltest.contract import Criterion, ServiceContract, contains
from baseltest.declarative._instantiate import OptimizePoint
from baseltest.engine import RunKind, RunPlan


def _contract() -> ServiceContract[str]:
    return ServiceContract(
        contract_id="c",
        invoke=lambda request: request,
        criteria=(Criterion(name="n", postconditions=(contains("a"),), threshold=0.5),),
        views={"upper": str.upper},
    )


def test_service_contract_views_are_read_only() -> None:
    with pytest.raises(TypeError):
        _contract().views["upper"] = str.lower  # type: ignore[index]


def test_criterion_characterisation_failure_distribution_is_read_only() -> None:
    record = CriterionCharacterisation(successes=1, trials=2, failure_distribution={"reason": 1})
    with pytest.raises(TypeError):
        record.failure_distribution["reason"] = 2  # type: ignore[index]


def test_baseline_record_views_are_read_only() -> None:
    record = BaselineRecord(
        contract_id="c",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        sample_count=10,
        inputs_identity="fp",
        criteria={},
        views={"body": "sha256:abc"},
    )
    with pytest.raises(TypeError):
        record.views["body"] = "sha256:def"  # type: ignore[index]


def test_optimize_point_configuration_is_read_only() -> None:
    point = OptimizePoint(
        parameters=None,
        configuration={"temperature": 0.7},
        contract=_contract(),
        plan=RunPlan(samples=10, inputs=("a",), kind=RunKind.TEST),
    )
    with pytest.raises(TypeError):
        point.configuration["temperature"] = 0.9  # type: ignore[index]


def test_caller_mutation_does_not_leak_in() -> None:
    supplied = {"reason": 1}
    record = CriterionCharacterisation(successes=1, trials=2, failure_distribution=supplied)
    supplied["reason"] = 999
    supplied["late"] = 7
    assert dict(record.failure_distribution) == {"reason": 1}
