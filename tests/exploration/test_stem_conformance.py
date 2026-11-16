"""The mavai-R exploration-stem conformance case.

``tests/conformance/interchange/naming-explore-stem.yaml`` is vendored from
the mavai-R interchange archive. Its ``bound`` part fixes the whole-stem
bound applied to a given stem (amendment 2026-11-04); its ``stems`` part
fixes the stem derived from ordered factors, which is also the document's
``configuration``.
"""

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from baseltest.exploration.writer import (
    _STEM_BOUND_HASH_LENGTH,
    _STEM_BYTE_CAP,
    _bounded,
    exploration_stem,
)

_CASE_PATH = (
    Path(__file__).parent.parent / "conformance" / "interchange" / "naming-explore-stem.yaml"
)
_CASE = YAML(typ="safe").load(_CASE_PATH.read_text(encoding="utf-8"))


def test_the_case_bound_matches_the_writer() -> None:
    assert _CASE["maxBytes"] == _STEM_BYTE_CAP
    assert _CASE["hashChars"] == _STEM_BOUND_HASH_LENGTH


@pytest.mark.parametrize("entry", _CASE["bound"], ids=lambda e: e["id"])
def test_bound_gives_the_expected_stem(entry: dict[str, Any]) -> None:
    assert _bounded(entry["stem"]) == entry["expected"]
    assert len(entry["expected"].encode("utf-8")) <= _STEM_BYTE_CAP


@pytest.mark.parametrize("entry", _CASE["stems"], ids=lambda e: e["id"])
def test_exploration_stem_gives_the_expected_stem(entry: dict[str, Any]) -> None:
    factors = tuple((factor["name"], factor["value"]) for factor in entry["factors"])
    assert exploration_stem(factors) == entry["expected"]
