"""The usage-bearing service reply — a response that is more than a string.

A binding or built-in service type may return a :class:`Reply` in place
of a bare response string: the text flows through views and criteria
exactly as a string would, and the token counts land on the run's cost
accounting (the artefact cost blocks' ``totalTokens``/
``avgTokensPerSample``, which the shared ``mavai`` renderer shows as
"ms · tok" cells). Token usage is an input to model decisions — the
counts price a configuration — so a language model's reply carries
them first-class; a plain string remains a complete response for every
service with no token notion.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Reply:
    """One service reply: the response text plus reported token usage.

    Attributes:
        text: The response text — judged by criteria exactly as a bare
            string response.
        input_tokens: Tokens the request consumed, when reported.
        output_tokens: Tokens the response produced, when reported.
    """

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        """Input plus output, when both were reported."""
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens
