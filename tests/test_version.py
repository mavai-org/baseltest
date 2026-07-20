"""The package version has a single source: the distribution metadata."""

import tomllib
from pathlib import Path

import baseltest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_packaged_version() -> None:
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert baseltest.__version__ == declared
