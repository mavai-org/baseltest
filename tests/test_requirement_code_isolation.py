"""Regression guard: internal tracking codes never appear in this repository.

Orchestrator planning documents use short letter-prefix codes for internal
feature tracking. A reader of this open-source code has no context for
them, so they must never appear in source — production or test. Features
are referred to by their domain names instead.

This file necessarily names the prefixes to be the guard, and is the only
permitted match site.
"""

import re
from pathlib import Path

_CODE_PATTERN = re.compile(r"\b(CT|EX|LT|PT|RC|RP|SC|SN|TH|UC|XM|DG|DA)\d{2}\b")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCANNED_ROOTS = (_REPO_ROOT / "src", _REPO_ROOT / "tests")
_SELF = Path(__file__).resolve()


def test_no_tracking_codes_in_source_or_tests() -> None:
    offenders: list[str] = []
    for root in _SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == _SELF or "__pycache__" in path.parts:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if _CODE_PATTERN.search(line):
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT)}:{line_number}: {line.strip()}"
                    )
    assert not offenders, (
        "internal tracking codes must not appear in source; refer to features "
        "by their domain names:\n" + "\n".join(offenders)
    )
