"""A rule-driven service whose identity lives partly on disk.

The triage assistant routes support requests using the keyword rules in
``triage-rules.txt``. That file is as much a part of the service's
identity as this code: change one rule and yesterday's baseline describes
a different service. Declaring the file's fingerprint as a covariate
makes the identity explicit — ``basel measure`` records it in the
baseline artefact, and a later ``basel test`` under edited rules is
refused with the drifted key named, instead of judging silently against
stale evidence.

Like the simulated-service example, the stochastic "unsure" branch is a
simulation (true routing rate ≈ 0.9) so the example runs offline.
"""

import hashlib
import random
from pathlib import Path

from baseltest.declarative import binding

_RULES_FILE = Path(__file__).parent / "triage-rules.txt"


def _parse_rules(text: str) -> dict[str, tuple[str, ...]]:
    rules: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        category, _, keywords = stripped.partition(":")
        rules[category.strip()] = tuple(k.strip() for k in keywords.split(","))
    return rules


_RULES_TEXT = _RULES_FILE.read_text(encoding="utf-8")
_RULES = _parse_rules(_RULES_TEXT)

# Resolved at import time — and the bindings file is imported afresh on
# every invocation, so the fingerprint always describes the file as it is
# now, not as it was when the baseline was measured.
_RULES_FINGERPRINT = hashlib.sha256(_RULES_TEXT.encode("utf-8")).hexdigest()[:12]


@binding(
    "triage-assistant",
    covariates={
        "triage-rules": _RULES_FINGERPRINT,
        "assistant-version": "1.0",
    },
)
def route_request(request: str) -> str:
    if random.random() >= 0.9:  # noqa: S311 — simulation, not cryptography
        return "the assistant is unsure — please route manually"
    lowered = request.lower()
    for category, keywords in _RULES.items():
        if any(keyword in lowered for keyword in keywords):
            return f"category: {category}"
    return "category: general"
