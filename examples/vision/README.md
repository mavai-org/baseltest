# Vision: sending an image to a multimodal model

This example shows the *encode-and-send* path: an input that mixes text and an
image is assembled into a multimodal request and sent to a real model. Each
input in `dominant-colour.yaml` is a multi-part message — a text instruction
beside an `image:` part; the framework base64-encodes the image into the
provider's content block (OpenAI's `image_url` data URI here) and the model's
answer is judged by the postconditions, exactly as a text response would be.

```bash
basel check dominant-colour.yaml    # validates offline — see below
basel test  dominant-colour.yaml    # runs against a real model — needs credentials
```

## It needs a real multimodal endpoint to run

Unlike the speech-to-text example (a local simulation), there is no way to
*run* this offline: the whole point is that a real model receives the image.
Point it at a vision-capable endpoint and give it a key:

```bash
export MAVAI_LLM_API_KEY=sk-...      # or OPENAI_API_KEY
basel test dominant-colour.yaml --samples 30
```

`basel check`, on the other hand, runs **entirely offline**: it assembles the
request, resolves the provider, and confirms the `image-input` capability is
declared — every load-time join short of the network. Drop the
`capabilities: [image-input]` line from `mavai-services.yaml` and `check`
refuses before any sample, naming the missing capability.

## The capability gate

A media modality is sent only when two things hold: the provider's protocol
can carry it, **and** the service declared the matching per-modality
capability (`image-input`, `document-input`, `audio-input`). An undeclared or
uncarriable modality is refused at load, never dropped silently — the same
discipline as `response-schema:`, `prompt-caching:`, and `thinking:`. Swap
`provider: openai` for `anthropic` and the image is re-encoded into Anthropic's
base64 source block instead; declare `audio-input` on a provider without an
audio block and it is refused at load.
