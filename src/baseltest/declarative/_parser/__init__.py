"""Parsing and validation: a contract file into a checked contract model.

Everything here happens at load time, before any invocation: structural
validation, reserved-key rejection with a pointer, the views block
(``raw`` reserved), subject/``path`` legality, per-input expectation
lists, and constructive refusals in format vocabulary.

The contract file is posture-free: the run mode (``test``/``measure``) is the
invocation verb, never a key.

This package is a thin facade over the concern-split submodules: the
declaration model and constants (`_model`), the low-level shape helpers
(`_shape`), the document structure and transforms (`_structure`), the
section parsers (`_forms`, `_inputs`, `_criteria`, `_latency`), and the
`parse_contract`/`load_contract` orchestrator (`_contract`).
"""

from ._contract import load_contract, parse_contract
from ._latency import _PERCENTILE_KEYS as _PERCENTILE_KEYS
from ._model import (
    FORMAT_IDENTIFIER,
    RAW_VIEW,
    ContractDeclaration,
    CriterionDeclaration,
    Form,
    FormDeclaration,
    LatencyDeclaration,
)

__all__ = [
    "FORMAT_IDENTIFIER",
    "RAW_VIEW",
    "ContractDeclaration",
    "CriterionDeclaration",
    "Form",
    "FormDeclaration",
    "LatencyDeclaration",
    "load_contract",
    "parse_contract",
]
