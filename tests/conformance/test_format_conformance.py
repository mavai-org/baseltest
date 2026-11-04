"""Loader conformance against the family's declarative format corpus.

The vendored corpus (``tests/conformance/formats/``, see NOTE.md there) is
the published oracle for the declarative formats: instance files with
expected outcomes, classified by ``manifest.yaml``. The manifest's binding
obligations are the outcome (loads / refused) and, for refusals, the
*category*; refusal message wording is informational, so the mapping from
each category to this loader's own message lives here, in
``_CATEGORY_MESSAGES``.

The conformance load is the format layer: for a contract file, parsing plus
the load-time expression-compilation walk (service-binding resolution is
environment, not format — the corpus holds under an empty user-registration
environment plus each case's ``requires:`` list); for a services file, the
full parse against a registry provisioned with exactly the corpus's
required registrations.

Selective assertion fails the build: the run records every case it
asserted and diffs that against the manifest's full obligation, and the
diff mechanism is itself exercised by mutation.

Declared exemptions: a case belonging to a format amendment this package
has not yet implemented is listed in ``_DECLARED_EXEMPTIONS``, naming its
category (or its ``loads`` outcome), the amendment, the open bundle that
owes it, and the date it was declared. An exempted case is expected to
fail and is reported as such (``xfail``, strict: it fails the build the
moment it passes, so the list can only shrink); the obligation diff counts
it as a declared exemption, never as silence; and a case that is neither
asserted nor declared still fails the build. With exemptions present this
package does not claim full conformance at the pinned release.
"""

# mavai-ref: JVI-YM9A27C — do not remove (resolves in mavai-orchestrator)

from dataclasses import dataclass
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from baseltest import Bindings
from baseltest.declarative._errors import ContractConfigurationError
from baseltest.declarative._instantiate._postconditions import (
    _build_criterion,
    _expected_postconditions,
)
from baseltest.declarative._instantiate._views import _build_views
from baseltest.declarative._parser import load_contract
from baseltest.declarative._services import parse_services

_FORMATS = Path(__file__).parent / "formats"
_CORPUS = _FORMATS / "corpus"

_MANIFEST = YAML(typ="safe").load((_FORMATS / "manifest.yaml").read_text(encoding="utf-8"))
_ENTRIES = {entry["file"]: entry for entry in _MANIFEST["corpus"]}


def _corpus_registry() -> Bindings:
    """The corpus's required registrations (the manifest's requires: names).

    Steppers (prompt-engineer, linear-sweep) and the pass-rate scorer are
    reader built-ins; the transform, check, and user type below are the
    corpus's only host-code requirements.
    """
    bindings = Bindings()

    @bindings.transform("basket-judge")
    def basket_judge(response: str) -> dict:
        return {"namesUnique": True}

    @bindings.check("looks-right")
    def looks_right(subject: str) -> bool:
        return True

    @bindings.binding_factory("triage")
    def triage(tone: str, certainty: float):
        def run(request: str) -> str:
            return "category: billing"

        return run

    @bindings.binding("echo")
    def echo(request: str) -> str:
        return request

    @bindings.scorer("politeness")
    def politeness(summary: object) -> float:
        return 0.0

    return bindings


@dataclass(frozen=True, slots=True)
class Exemption:
    """One declared exemption: a corpus case this package does not yet meet.

    Attributes:
        category: The case's refusal category, or ``loads`` for a valid case.
        amendment: The format amendment the case belongs to.
        owed_by: The open bundle that owes the implementation.
        declared: When the exemption was declared.
    """

    category: str
    amendment: str
    owed_by: str
    declared: str


_RUN_CONTROLS = "mavai-services/1 run controls (pacing:, budget:), amendment 2026-10-13"
_RUN_CONTROLS_BUNDLE = "work/2026-10-13-baseltest-declarative-resource-controls"
_DECLARED_ON = "2026-11-03"

# Cases of amendments this package has not implemented yet. Each must name
# a manifest case and fail as expected; the list only shrinks.
_DECLARED_EXEMPTIONS = {
    file_name: Exemption(category, _RUN_CONTROLS, _RUN_CONTROLS_BUNDLE, _DECLARED_ON)
    for file_name, category in (
        ("budget-in-configuration.yaml", "budget-in-configuration"),
        ("budget-in-exploration.yaml", "budget-in-exploration"),
        ("budget-in-optimization-initial.yaml", "budget-in-optimization-initial"),
        ("budget-limit-missing.yaml", "budget-limit-missing"),
        ("budget-limit-not-positive.yaml", "budget-limit-not-positive"),
        ("budget-on-exhausted-vocabulary.yaml", "budget-on-exhausted-vocabulary"),
        ("budget-unknown-key.yaml", "budget-unknown-key"),
        ("pacing-empty.yaml", "pacing-empty"),
        ("pacing-rate-not-positive.yaml", "pacing-rate-not-positive"),
        ("pacing-unknown-key.yaml", "pacing-unknown-key"),
        ("services-run-controls.yaml", "loads"),
        ("services-run-controls-bare.yaml", "loads"),
        ("services-run-controls-budget.yaml", "loads"),
        ("services-run-controls-pacing.yaml", "loads"),
    )
}


# category -> a fragment of THIS loader's refusal message. Informational by
# the manifest's contract (categories bind, wording does not); the fragment
# check is what makes a wrong-reason refusal fail rather than pass.
_CATEGORY_MESSAGES = {
    # mavai-contract/1
    "format-identifier": "`format:` must be",
    "missing-required-key": "missing required key",
    "unknown-key": "unknown key",
    "reserved-seam-key": "reserved by the mavai contract format",
    "withdrawn-sizing-key": "the contract carries the claim",
    "withdrawn-run-mode-key": "`kind:` was withdrawn",
    "threshold-range": "`threshold:` must be a number in (0, 1)",
    "threshold-empirical-reserved": "`threshold: empirical` is reserved",
    "tolerate-with-threshold": "no baseline claim to protect",
    "criterion-confidence-with-threshold": "belongs to an empirical",
    "threshold-origin-vocabulary": "provenance category",
    "criterion-without-form": "declares no postcondition form",
    "postcondition-form-cardinality": "exactly one form",
    "default-view-unresolvable": "no default view is resolvable",
    "optional-slack-malformed": "a bare fraction is never guessed at",
    "optional-operand": "required is the default, not a spelling",
    "optional-on-parses": "would be inert",
    "path-on-non-string-form": "string and value-comparison forms only",
    "parses-with-in": "takes no `in:`",
    "parses-in-expected": "criterion-level form",
    "raw-view-declared": "reserved name of the untransformed response",
    "inputs-empty": "`inputs:` must be a non-empty list",
    "criteria-empty": "`criteria:` must be a non-empty list",
    "input-list-mixed": "not a mix",
    "input-part-unknown": "unknown input part",
    "input-entry-extra-key": "single-key mapping",
    "intent-vocabulary": "unknown `intent",
    "confidence-range": "`confidence:` must be a number in (0, 1)",
    "latency-shape-contradiction": "contradictory",
    "latency-without-bounds": "declares no bounds",
    "latency-ceiling-not-positive": "positive whole number of milliseconds",
    "latency-percentile-vocabulary": "unknown percentile",
    "view-undeclared": "names an undeclared view",
    "parses-view-undeclared": "`parses:` references a declared view",
    "expected-requires-single-criterion": "exactly one criteria entry",
    "selection-expression-invalid": "not a valid JSONPath",
    "latency-ceilings-decreasing": "non-decreasing",
    "input-file-unreadable": "cannot read input file",
    "set-form-without-path": "requires a `path:` under a declared view",
    "value-operand-malformed": "takes a number or a numeric string",
    "is-null-operand": "takes the literal `true`",
    "set-operand-empty": "non-empty list of scalar values",
    "set-of-without-optional": "— say that",
    "set-of-min-present-malformed": "a bare fraction is never guessed at",
    "set-of-lists-overlap": "in both `required:` and `optional:`",
    "set-of-min-present-bounds": "the `optional:` list's distinct size",
    "is-operand-not-boolean": "`is:` takes a boolean",
    "roots-block-malformed": "`roots:` must be a non-empty mapping",
    "roots-name-shape": "must match [a-z][a-z0-9-]*",
    "roots-value-malformed": "root `corpus:`",
    "roots-reference-undeclared": "references an undeclared root",
    "roots-dead-declaration": "referenced by nothing in the file",
    "roots-directory-missing": "not an existing directory",
    # mavai-services/1
    "services-format-identifier": "`format:` must be",
    "services-block-missing": "`services:` must be a non-empty mapping",
    "configuration-missing": "`configuration:` block is required",
    "parameter-outside-configuration": "belongs inside the `configuration:`",
    "definition-unknown-key": "unknown key",
    "top-level-unknown-key": "unknown key",
    "lm-system-prompt-missing": "`system-prompt:` is required",
    "lm-configuration-unknown-key": "unknown key",
    "lm-provider-vocabulary": "provider",
    "lm-thinking-vocabulary": "`thinking:` must be one of",
    "lm-top-p-range": "`top-p:` must be a number in (0, 1]",
    "lm-prompt-caching-type": "`prompt-caching:` must be a boolean",
    "lm-max-tokens-range": "`max-tokens:` must be a whole number",
    "lm-capabilities-vocabulary": "capabilit",
    "explorations-empty": "`explorations:` must be a non-empty list",
    "exploration-entry-null-value": "declares no value",
    "optimization-entry-unknown-key": "unknown key",
    "optimization-stepper-missing": "`stepper:` is required",
    "optimization-max-iterations-missing": "`max-iterations:` is required",
    "optimization-max-iterations-not-positive": "must be a positive integer",
    "optimization-id-shape": "letters, digits, dots",
    "type-unresolved": "unknown `type:",
    "exploration-duplicate-point": "distinct covariate point",
    "optimization-duplicate-id": "already used",
    "optimization-id-required-when-multiple": "`id:` is required when",
    "optimization-initial-restates-baseline": "merely restates",
    "lm-system-prompt-file-malformed": "file form is `{file: <path>}`",
    "services-roots-reference-undeclared": "references an undeclared root",
    "lm-deadline-range": "`deadline-ms:` must be a whole number of milliseconds",
    "stepper-config-unknown-key": "`stepper-config:` has unknown key",
    "stepper-linear-sweep-zero-step": "`step:` must be non-zero",
    "stepper-refining-grid-bounds": "must be below `hi:`",
    "stepper-refining-grid-min-step": "with `min-step:` at most `step:`",
    "stepper-refining-grid-objective": "`objective:` must be 'maximize'",
    "stepper-refining-grid-prefer": "`prefer:` must be 'low' or 'high'",
    "stepper-refining-grid-scorer": "`scorer:` must be 'pass-rate'",
    # mavai-contract/1, zero-failures criteria (amendment 2026-11-03)
    "zero-failures-with-threshold": "a zero-failures criterion has no rate to require",
    "zero-failures-with-tolerate": "a zero-failures criterion has no baseline risk claim",
    "zero-failures-with-confidence": "a zero-failures criterion has no confidence level",
    "zero-failures-not-boolean": "`zero-failures:` takes a boolean",
}


def _load(entry: dict) -> None:
    """Drive the format-layer load for one corpus case; raise its refusal."""
    directory = "valid" if entry["outcome"] == "loads" else "invalid"
    path = _CORPUS / directory / entry["file"]
    bindings = _corpus_registry()
    if entry["format"] == "mavai-contract/1":
        # Parse, then the load-time construction of views and postconditions
        # — where transform names resolve and every selection expression
        # compiles eagerly. Service-binding resolution and run-mode sizing
        # are deliberately not driven: they are environment and invocation
        # concerns, outside the format layer the corpus binds.
        declaration = load_contract(path)
        registry = bindings._registry
        _build_views(declaration, registry)
        expected = _expected_postconditions(
            declaration.expected_pairs, declaration.transforms, registry
        )
        for criterion in declaration.criteria:
            _build_criterion(
                criterion, declaration.confidence, expected, declaration.transforms, registry
            )
    else:
        parse_services(path.read_text(encoding="utf-8"), bindings._registry, path)


def _assert_case(entry: dict) -> None:
    """One case's binding obligations: the outcome, and the category's refusal."""
    if entry["outcome"] == "loads":
        _load(entry)
        return
    category = entry["category"]
    fragment = _CATEGORY_MESSAGES[category]
    with pytest.raises(ContractConfigurationError) as refusal:
        _load(entry)
    assert fragment in str(refusal.value), (
        f"{entry['file']}: refused, but not as {category!r} — expected the "
        f"message to carry {fragment!r}, got: {refusal.value}"
    )


def _diff_against_obligations(asserted: set[str], exempted: set[str]) -> None:
    """The selective-assertion gate: every manifest case must have been
    asserted, or declared exempt — never silently left out."""
    missing = set(_ENTRIES) - asserted - exempted
    assert not missing, (
        "format-conformance run did not assert every manifest obligation — "
        f"missing: {', '.join(sorted(missing))}"
    )


@pytest.mark.parametrize("file_name", sorted(_ENTRIES))
def test_corpus_case(file_name: str) -> None:
    exemption = _DECLARED_EXEMPTIONS.get(file_name)
    if exemption is None:
        _assert_case(_ENTRIES[file_name])
        return
    try:
        _assert_case(_ENTRIES[file_name])
    except (AssertionError, ContractConfigurationError, KeyError) as failure:
        pytest.xfail(
            f"declared exemption ({exemption.declared}): {exemption.category} — "
            f"{exemption.amendment}; owed by {exemption.owed_by} ({type(failure).__name__})"
        )
    pytest.fail(
        f"{file_name} is declared exempt but now meets its obligation — remove its "
        "exemption (the list only shrinks)"
    )


def test_every_manifest_obligation_is_asserted() -> None:
    # The parametrisation above is generated from the manifest itself, so a
    # skipped case means a deselected test, not a silent gap; this diff makes
    # the obligation explicit and machine-checked in one place. A declared
    # exemption is counted and reported, never silent.
    asserted = set()
    for file_name, entry in _ENTRIES.items():
        if file_name in _DECLARED_EXEMPTIONS:
            continue
        _assert_case(entry)
        asserted.add(file_name)
    exempted = set(_DECLARED_EXEMPTIONS)
    _diff_against_obligations(asserted, exempted)
    print(
        f"format conformance: {len(asserted)} of {len(_ENTRIES)} manifest cases asserted, "
        f"{len(exempted)} declared exempt"
    )


def test_selective_assertion_fails_the_build() -> None:
    # Mutation check of the gate itself: dropping one undeclared case from
    # the asserted set must fail the obligation diff.
    dropped = next(name for name in sorted(_ENTRIES) if name not in _DECLARED_EXEMPTIONS)
    with pytest.raises(AssertionError, match=dropped):
        _diff_against_obligations(set(_ENTRIES) - {dropped}, set(_DECLARED_EXEMPTIONS))


def test_a_declared_exemption_is_counted_not_silent() -> None:
    # Mutation check of the exemption: an exempted case passes the diff only
    # because it is declared — remove the declaration and the same omission
    # fails the build.
    assert _DECLARED_EXEMPTIONS, "no exemptions are declared; drop this mutation check"
    exempt = next(iter(sorted(_DECLARED_EXEMPTIONS)))
    asserted = set(_ENTRIES) - {exempt}
    _diff_against_obligations(asserted, {exempt})
    with pytest.raises(AssertionError, match=exempt):
        _diff_against_obligations(asserted, set())


def test_declared_exemptions_name_manifest_cases_with_their_category() -> None:
    for file_name, exemption in _DECLARED_EXEMPTIONS.items():
        entry = _ENTRIES.get(file_name)
        assert entry is not None, f"exemption names no manifest case: {file_name}"
        assert exemption.category == entry.get("category", "loads"), file_name
        assert exemption.owed_by and exemption.amendment and exemption.declared, file_name


def test_zero_failures_cases_are_asserted_not_exempted() -> None:
    # The amendment this package implements is never exempted.
    zero_failures = {
        name for name, entry in _ENTRIES.items() if "zero-failures" in entry.get("spec", "")
    } | {name for name in _ENTRIES if name.startswith("zero-failures-")}
    assert zero_failures
    assert not zero_failures & set(_DECLARED_EXEMPTIONS)


def test_manifest_mirrors_the_vendored_tree() -> None:
    on_disk = {p.name for d in ("valid", "invalid") for p in (_CORPUS / d).glob("*.yaml")}
    assert on_disk == set(_ENTRIES)


def test_every_category_has_a_case_and_a_message_mapping() -> None:
    manifest_categories = set(_MANIFEST["categories"])
    exercised = {e["category"] for e in _ENTRIES.values() if e["outcome"] == "refused"}
    assert exercised == manifest_categories
    exempt_categories = {e.category for e in _DECLARED_EXEMPTIONS.values()} - {"loads"}
    assert set(_CATEGORY_MESSAGES) == manifest_categories - exempt_categories
