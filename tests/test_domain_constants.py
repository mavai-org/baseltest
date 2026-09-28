"""Domain defaults are single-sourced and consumed, not re-declared.

Each default the framework carries — the statistical confidence level and
detection power, the latency percentile vocabulary, the verdict namespace,
the stock-transform names — is defined once and imported everywhere else.
These tests lock the consumption: a routine that re-hardcodes ``0.95``, or a
second copy of the percentile keys or the namespace, drifts from the single
source and fails here rather than silently diverging later.
"""

import inspect

from baseltest.contract.model import PERCENTILE_LEVELS
from baseltest.declarative import _parser, _registry, _structured
from baseltest.engine import METHODOLOGY_VERSION as ENGINE_METHODOLOGY_VERSION
from baseltest.reporting import console, verdict_reader, verdict_xml
from baseltest.statistics import (
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_POWER,
    METHODOLOGY_VERSION,
    wilson_interval,
    wilson_lower_bound,
    wilson_lower_bound_from_rate,
)


def _default(func: object, parameter: str) -> object:
    return inspect.signature(func).parameters[parameter].default  # type: ignore[arg-type]


def test_statistics_confidence_defaults_bind_to_the_shared_constant() -> None:
    for func in (
        wilson_interval,
        wilson_lower_bound,
        wilson_lower_bound_from_rate,
    ):
        assert _default(func, "confidence_level") == DEFAULT_CONFIDENCE_LEVEL


def test_the_sizing_resolver_defaults_to_the_shared_power() -> None:
    from baseltest.declarative._sizing import _resolve

    assert _resolve.DEFAULT_POWER is DEFAULT_POWER


def test_the_methodology_version_is_one_constant() -> None:
    # Reporting reads it through the engine; neither restates the literal.
    assert ENGINE_METHODOLOGY_VERSION is METHODOLOGY_VERSION
    assert console.METHODOLOGY_VERSION is METHODOLOGY_VERSION
    assert verdict_xml.METHODOLOGY_VERSION is METHODOLOGY_VERSION


def test_percentile_keys_derive_from_the_level_map() -> None:
    assert tuple(PERCENTILE_LEVELS) == _parser._PERCENTILE_KEYS


def test_verdict_reader_namespace_derives_from_the_writer() -> None:
    assert f"{{{verdict_xml._NAMESPACE}}}" == verdict_reader._NS


def test_stock_transform_names_derive_from_the_transform_table() -> None:
    assert tuple(_structured.STOCK_TRANSFORMS) == _registry._STOCK_TRANSFORMS
