"""Every anticipated error shares one base; defects deliberately do not.

A caller can catch the whole family of on-purpose failures with a single
``except BaseltestError``. The two defect carriers — a bug escaping a trial,
and its enriched diagnosis — must stay *outside* that base, or ``except
BaseltestError`` would silently swallow a bug it was never meant to catch.
"""

from baseltest.contract import (
    BaseltestError,
    ContractValidationError,
    PreconditionError,
    ServiceDeliveryError,
    TransformError,
    TrialDefectError,
)
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._providers import ProviderResponseError
from baseltest.declarative._sizing import SizingRefusalError
from baseltest.engine import DefectDiagnosisError, InfeasibleRunError

DOMAIN_ERRORS = (
    TransformError,
    ServiceDeliveryError,
    InfeasibleRunError,
    SizingRefusalError,
    ContractConfigurationError,
    ProviderResponseError,
    PreconditionError,
    ContractValidationError,
)

DEFECT_ERRORS = (TrialDefectError, DefectDiagnosisError)


def test_every_domain_error_is_a_baseltest_error() -> None:
    for error in DOMAIN_ERRORS:
        assert issubclass(error, BaseltestError)


def test_defects_are_not_baseltest_errors() -> None:
    for defect in DEFECT_ERRORS:
        assert not issubclass(defect, BaseltestError)


def test_a_domain_error_is_caught_by_the_base() -> None:
    try:
        raise ServiceDeliveryError("upstream 503")
    except BaseltestError as caught:
        assert str(caught) == "upstream 503"
