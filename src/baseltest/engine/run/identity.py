"""Input identity: a stable, order-insensitive fingerprint of an input list."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any


def inputs_fingerprint(inputs: Sequence[Any]) -> str:
    """A stable, order-insensitive fingerprint of an input list.

    All-string lists keep their historical canonical form, so existing
    baselines stay addressable; mixed or structured inputs canonicalise
    each entry as JSON before sorting.
    """
    if all(isinstance(entry, str) for entry in inputs):
        canonical = json.dumps(sorted(inputs), ensure_ascii=False)
    else:
        encoded = sorted(
            json.dumps(list(e) if isinstance(e, tuple) else e, ensure_ascii=False) for e in inputs
        )
        # An object wrapper, so a structured corpus can never collide with
        # the historical all-string array form.
        canonical = json.dumps({"typed-inputs": encoded}, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
