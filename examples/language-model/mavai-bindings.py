"""Bindings for the basket-builder: a tiny in-process judge.

``mavai-services.yaml`` already defines the service; this file (discovered
beside the contract, exactly like the services file) adds a custom
transformation. A ``@transform`` returning structure — a dict or list —
produces a view as structurally addressable as any stock ``json`` view:
contract checks select into it with a ``$``-rooted ``path:``.
"""

import json

from baseltest.contract import TransformError
from baseltest.declarative import Bindings

# The loader discovers registrations through this name.
bindings = Bindings()


@bindings.transform("basket-judge")
def basket_judge(raw: str) -> dict[str, object]:
    """Derived facts about the basket that no single raw field states."""
    try:
        items = json.loads(raw)["items"]
    except (ValueError, TypeError, KeyError) as error:
        raise TransformError(f"response is not a basket: {error}") from error
    if not isinstance(items, list):
        raise TransformError("response is not a basket: items is not a list")
    names = [item.get("name") for item in items if isinstance(item, dict)]
    return {"namesUnique": len(names) == len(set(names))}
