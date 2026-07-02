"""Enforces that `baseltest.statistics` has no dependency on any other
`baseltest` package.

This is a plain AST-based import check rather than a dedicated tool
(`import-linter` or similar) -- the package boundary is small enough that
walking each module's import statements is simpler than configuring and
maintaining an external tool for a single rule.
"""

import ast
from pathlib import Path

import baseltest.statistics

_PACKAGE_ROOT = Path(baseltest.statistics.__file__).parent


def _imported_module_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            names.add(node.module)
    return names


def test_statistics_package_imports_nothing_from_other_baseltest_packages() -> None:
    offending: list[tuple[Path, str]] = []

    for source_path in _PACKAGE_ROOT.rglob("*.py"):
        for module_name in _imported_module_names(source_path):
            is_baseltest_import = module_name == "baseltest" or module_name.startswith("baseltest.")
            is_statistics_subpackage = module_name.startswith("baseltest.statistics")
            if is_baseltest_import and not is_statistics_subpackage:
                offending.append((source_path, module_name))

    assert not offending, f"baseltest.statistics must not import outside itself: {offending}"
