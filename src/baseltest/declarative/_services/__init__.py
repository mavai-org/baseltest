"""Declarative service definitions: the mavai-services/1 companion file.

A service file defines named services that contract files reference by
name. Each entry is a named, configured instance of a **service type** —
a registered implementation: the built-in ``language-model``, or a user
type registered in ``mavai-bindings.py``. A definition carries a complete
``configuration:`` block — the baseline factor record: every covariate
value the service runs under, in one place, communicated to the service
uniformly. An optional ``explorations:`` section extends the baseline
into a configuration grid: each entry declares only the covariates that
deviate from the baseline (entry = baseline with those keys replaced),
and the grid is the baseline plus the entries. A test or measure run
consumes exactly the baseline; an explore run consumes the whole grid.

The grid semantics here are one generic layer; everything type-specific —
configuration validation, canonical key order, provenance projection, the
invoker — is supplied by the type's registry entry. ``language-model`` is
simply the first built-in entry on that seam.

This package is a thin facade over the concern-split submodules: the value
model and grid projection (`_model`), the built-in ``language-model`` type
(`_language_model`), and the services-file parsing (`_parse`).
"""

from ._language_model import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS_CEILING,
    LanguageModelParameters,
    resolved_provenance,
)
from ._language_model import _language_model_type as _language_model_type
from ._language_model import _validate_configuration as _validate_configuration
from ._model import ServiceDefinition, configuration_values, factor_values
from ._parse import _resolved_point as _resolved_point
from ._parse import discover_services, parse_services

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "MAX_TOKENS_CEILING",
    "LanguageModelParameters",
    "ServiceDefinition",
    "configuration_values",
    "discover_services",
    "factor_values",
    "parse_services",
    "resolved_provenance",
]
