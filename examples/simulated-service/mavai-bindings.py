"""A simulated stochastic service: no network, no key, runs anywhere.

The "fortune teller" answers most requests helpfully but, like any
stochastic service, sometimes does not. Its true success rate is about
0.9 — which is the whole point: run the example twice and the observed
rate will differ, while the verdict stays honest about what the evidence
supports.
"""

import random

from baseltest.declarative import binding

_FORTUNES = [
    "Good fortune: {} will find what was lost.",
    "The signs favour {} today.",
    "A pleasant surprise awaits {}.",
]


@binding("fortune-teller")
def tell_fortune(name: str) -> str:
    if random.random() < 0.9:  # noqa: S311 — simulation, not cryptography
        return random.choice(_FORTUNES).format(name)  # noqa: S311
    return f"The spirits are silent about {name}."
