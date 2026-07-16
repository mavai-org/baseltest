"""A rule-driven service whose identity lives partly on disk — and partly in YAML.

The triage assistant routes support requests using the keyword rules in
``triage-rules.txt``. Its identity has two feeds:

- **Computed covariates**, declared here: the rules file's fingerprint and
  the assistant version — values a services file cannot state. Change a
  rule and yesterday's baseline describes a different service; the next
  ``basel test`` is refused with the drifted key named.
- **Declared configuration**, in ``mavai-services.yaml``: the factory
  below is registered as the service *type* ``triage``, and its signature
  is the configuration schema — ``tone`` and ``certainty`` are the
  services file's keys. ``basel explore`` runs the whole grid; ``test``
  and ``measure`` run the baseline configuration, whose keys join the
  same drift-checked identity.

Like the simulated-service example, the stochastic "unsure" branch is a
simulation — ``certainty`` is the true routing rate, so exploring it
shows honestly different observed rates, offline.
"""

import hashlib
import random
from collections.abc import Callable
from pathlib import Path

from baseltest.declarative import binding_factory

_RULES_FILE = Path(__file__).parent / "triage-rules.txt"

_CLOSINGS = {
    "matter-of-fact": "routed",
    "reassuring": "we'll take good care of this",
}


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


@binding_factory(
    "triage",
    covariates={
        "triage-rules": _RULES_FINGERPRINT,
        "assistant-version": "2.0",
    },
)
def triage(tone: str = "matter-of-fact", certainty: float = 0.9) -> Callable[[str], str]:
    closing = _CLOSINGS.get(tone, _CLOSINGS["matter-of-fact"])

    def route_request(request: str) -> str:
        if random.random() >= certainty:  # noqa: S311 — simulation, not cryptography
            return "the assistant is unsure — please route manually"
        lowered = request.lower()
        for category, keywords in _RULES.items():
            if any(keyword in lowered for keyword in keywords):
                return f"category: {category} — {closing}"
        return f"category: general — {closing}"

    return route_request
