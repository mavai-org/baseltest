"""Manifest-driven conformance coverage accounting.

The mavai-R oracle publishes ``manifest.json`` alongside its fixture
suites: per-suite case rosters, a binding-vs-informational classification
of every expected field, per-suite content hashes, and a family-mandatory
suite tier. The obligation on a consumer is the set of
``(suite, case, binding-field)`` triples across the family-mandatory tier
plus this repository's committed scope file — and the obligation is
*self-verified*: every conformance assertion records the triple it
asserted, and a final check diffs the recorded set against the manifest.
A binding field that is loaded but never asserted is a gap, not a pass.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPORT_PATH = Path(__file__).parents[2] / "build" / "conformance-report.json"

Triple = tuple[str, str, str]


def _as_list(value: Any) -> list[str]:
    # The oracle's serialiser unboxes single-element vectors to scalars.
    return [value] if isinstance(value, str) else list(value)


class ConformanceLedger:
    """Accumulates asserted (suite, case, binding-field) triples and diffs
    them against the manifest's obligations."""

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self._fixtures_dir = fixtures_dir
        self.manifest: dict[str, Any] = json.loads((fixtures_dir / "manifest.json").read_text())
        scope = json.loads((fixtures_dir / "SCOPE.json").read_text())
        self.scope_suites: tuple[str, ...] = tuple(scope["suites"])
        self.mandatory_suites: tuple[str, ...] = tuple(self.manifest["familyMandatory"])
        self.asserted: set[Triple] = set()

    # -- recording ---------------------------------------------------------

    def record(self, suite: str, case_name: str, field: str) -> None:
        """Record that one binding field of one case was asserted."""
        self.asserted.add((suite, case_name, field))

    # -- the obligation ----------------------------------------------------

    @property
    def in_scope_suites(self) -> tuple[str, ...]:
        """Family-mandatory plus committed scope, deduplicated, manifest order."""
        wanted = set(self.mandatory_suites) | set(self.scope_suites)
        return tuple(name for name in self.manifest["suites"] if name in wanted)

    def binding_fields(self, suite: str) -> frozenset[str]:
        return frozenset(_as_list(self.manifest["suites"][suite]["bindingFields"]))

    def obligations(self, suites: tuple[str, ...] | None = None) -> set[Triple]:
        """Every (suite, case, binding-field) triple the given suites demand.

        A case owes exactly the binding fields present in its own
        ``expected`` block — suites whose case groups carry different
        expected shapes (e.g. threshold_derivation's two approaches) owe
        per-case, not the suite-wide union.
        """
        out: set[Triple] = set()
        for suite in suites if suites is not None else self.in_scope_suites:
            binding = self.binding_fields(suite)
            for case in self._suite_cases(suite):
                out.update(
                    (suite, case["name"], field) for field in case["expected"] if field in binding
                )
        return out

    def gaps(self) -> set[Triple]:
        return self.obligations() - self.asserted

    def unaddressed_suites(self) -> list[tuple[str, int]]:
        """Manifest suites outside scope, with their case counts — reported,
        never silently skipped."""
        in_scope = set(self.in_scope_suites)
        return [
            (name, entry["caseCount"])
            for name, entry in self.manifest["suites"].items()
            if name not in in_scope
        ]

    # -- vendoring drift ---------------------------------------------------

    def vendored_md5(self, suite: str) -> str:
        filename = self.manifest["suites"][suite]["file"]
        return hashlib.md5((self._fixtures_dir / filename).read_bytes()).hexdigest()

    def manifest_md5(self, suite: str) -> str:
        return str(self.manifest["suites"][suite]["md5"])

    # -- the standing ------------------------------------------------------

    def standing(self) -> str:
        """The one-line summary every conformance run prints."""
        mandatory = self.obligations(self.mandatory_suites)
        scoped = self.obligations(tuple(s for s in self.scope_suites))
        unaddressed = self.unaddressed_suites()
        parts = [
            f"fixtures v{self.manifest['fixtureVersion']}",
            f"mandatory {len(mandatory & self.asserted)}/{len(mandatory)} binding assertions"
            f" over {len(self.mandatory_suites)} suites",
            f"scope {len(scoped & self.asserted)}/{len(scoped)}"
            f" over {len(self.scope_suites)} suites",
        ]
        if unaddressed:
            named = ", ".join(f"{name} ({count})" for name, count in unaddressed)
            parts.append(f"unaddressed: {named}")
        return "conformance standing: " + "; ".join(parts)

    def report(self) -> dict[str, Any]:
        """The machine-readable per-run report, for CI surfacing."""
        gaps = sorted(self.gaps())
        return {
            "fixtureVersion": self.manifest["fixtureVersion"],
            "manifestVersion": self.manifest["manifestVersion"],
            "mandatorySuites": list(self.mandatory_suites),
            "scopeSuites": list(self.scope_suites),
            "assertedTriples": len(self.asserted),
            "obligedTriples": len(self.obligations()),
            "gaps": [{"suite": s, "case": c, "field": f} for s, c, f in gaps],
            "unaddressedSuites": [
                {"suite": name, "caseCount": count} for name, count in self.unaddressed_suites()
            ],
            "standing": self.standing(),
        }

    def write_report(self, path: Path = REPORT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.report(), indent=2) + "\n")

    # -- internals ---------------------------------------------------------

    def _suite_cases(self, suite: str) -> list[dict[str, Any]]:
        filename = self.manifest["suites"][suite]["file"]
        return list(json.loads((self._fixtures_dir / filename).read_text())["cases"])
