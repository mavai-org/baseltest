"""A speech-to-text service whose input is an audio *file*, not a string.

The contract's inputs are ``audio:`` parts, so the framework hands this
binding a :class:`baseltest.FileInput` — the resolved path, the declared
kind, the bytes read once, and their content hash — and the binding opens
it and transcribes. Here the "transcription" is a local simulation (no
network, no key, no model): a small ASR that recovers each clip's
utterance most of the time and occasionally slips, so — like any
stochastic service — the observed accuracy varies while the verdict stays
honest about what the evidence supports.

The audio bytes feed the baseline's inputs identity by content, not path:
swap a clip's bytes and the next ``basel test`` measures a different
corpus.
"""

import random

from baseltest import FileInput
from baseltest.declarative import Bindings

# The reference utterance each clip stands for. A real service would decode
# the audio; this simulation keys off the delivered file's name rather than
# its waveform, so it is indifferent to whether the clip is a placeholder
# tone or a real recording (see README).
_TRANSCRIPTS = {
    "clip-01.m4a": "the quick brown fox",
    "clip-02.m4a": "Basel is a beautiful city",
    "clip-03.m4a": "testing one two three",
}

# The loader discovers registrations through this name.
bindings = Bindings()


@bindings.binding("stt")
def transcribe(audio: FileInput) -> str:
    """Transcribe one audio clip. The argument is the file itself."""
    reference = _TRANSCRIPTS.get(audio.path.name, "")
    if random.random() < 0.95:  # noqa: S311 — simulation, not cryptography
        return reference
    # A slip: the last word is dropped, as a real ASR might under noise.
    return reference.rsplit(" ", 1)[0]
