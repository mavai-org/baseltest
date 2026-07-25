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
"""

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

    return bindings


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
    "path-without-in": "`path:` requires `in:`",
    "path-on-non-string-form": "string forms only",
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
        parse_services(path.read_text(encoding="utf-8"), bindings._registry)


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


def _diff_against_obligations(asserted: set[str]) -> None:
    """The selective-assertion gate: every manifest case must have been asserted."""
    missing = set(_ENTRIES) - asserted
    assert not missing, (
        "format-conformance run did not assert every manifest obligation — "
        f"missing: {', '.join(sorted(missing))}"
    )


@pytest.mark.parametrize("file_name", sorted(_ENTRIES))
def test_corpus_case(file_name: str) -> None:
    _assert_case(_ENTRIES[file_name])


def test_every_manifest_obligation_is_asserted() -> None:
    # The parametrisation above is generated from the manifest itself, so a
    # skipped case means a deselected test, not a silent gap; this diff makes
    # the obligation explicit and machine-checked in one place.
    asserted = set()
    for file_name, entry in _ENTRIES.items():
        _assert_case(entry)
        asserted.add(file_name)
    _diff_against_obligations(asserted)


def test_selective_assertion_fails_the_build() -> None:
    # Mutation check of the gate itself: dropping one category's case from
    # the asserted set must fail the obligation diff.
    dropped = next(iter(sorted(_ENTRIES)))
    with pytest.raises(AssertionError, match=dropped):
        _diff_against_obligations(set(_ENTRIES) - {dropped})


def test_manifest_mirrors_the_vendored_tree() -> None:
    on_disk = {p.name for d in ("valid", "invalid") for p in (_CORPUS / d).glob("*.yaml")}
    assert on_disk == set(_ENTRIES)


def test_every_category_has_a_case_and_a_message_mapping() -> None:
    manifest_categories = set(_MANIFEST["categories"])
    exercised = {e["category"] for e in _ENTRIES.values() if e["outcome"] == "refused"}
    assert exercised == manifest_categories
    assert set(_CATEGORY_MESSAGES) == manifest_categories
