# Speech-to-text: a file-sourced input example

This example exists to show one thing: a contract input can be an **audio
file** rather than a string. Each input in `transcription.yaml` is an
`audio:` part naming a clip on disk; the framework resolves the path
(relative to the contract), reads the bytes once, folds their content hash
into the baseline's inputs identity, and hands the bound `stt` service a
`FileInput`. The service returns a transcript, judged by the postconditions
exactly as any text response would be.

```bash
basel test transcription.yaml                  # verdict at n = 5 (smoke)
basel test transcription.yaml --samples 200    # a tighter interval
basel measure transcription.yaml --samples 200 # characterisation + baseline
basel check transcription.yaml                 # loads and validates — incl. that the clips are readable
```

## The corpus, and why the transcriber is a simulation

`audio/` holds three short spoken clips:

| Clip | Utterance |
|------|-----------|
| `clip-01.m4a` | the quick brown fox |
| `clip-02.m4a` | Basel is a beautiful city |
| `clip-03.m4a` | testing one two three |

**The `stt` binding is a local simulation** (see `mavai-bindings.py`). It
does *not* decode the audio: it looks up each clip's reference transcript
*by filename* and returns it most of the time, occasionally dropping the
last word — a stochastic service whose observed accuracy varies run to run,
which is the whole point of measuring it. (Decoding real speech would need a
real ASR; that is exactly the body you would drop into `transcribe`.)

Because identity is content-based, replacing a clip's bytes changes the
baseline's inputs identity — a re-measure is then measuring a different
corpus, by design.

Swap in a real STT SDK or cloud call inside the binding and the contract,
the file delivery, and the identity behaviour are unchanged — only the body
of `transcribe` differs. That substitution is the capability this example
demonstrates.
