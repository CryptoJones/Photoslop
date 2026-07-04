# Model Backends — bring your own model

Photoslop never hardwires a model. The features that want one — **Select
Subject** and **Generative Fill** — route through a pluggable `ModelAdapter`,
and you connect whatever you run.

## Configure
Edit → Options → **Model Backend…**: pick an adapter and (for the HTTP adapter) enter
your server's base URL. CLI: `--model-url URL` before any model op.

## The generic HTTP contract
JSON with base64-encoded PNGs. Three endpoints under your base URL:

```
POST <base>/select-subject
  {"image": "<b64 png>"}                       → {"mask": "<b64 png>"}   # white = subject

POST <base>/generative-fill
  {"image": "<b64 png>", "mask": "<b64 png>", "prompt": "…"}
                                               → {"image": "<b64 png>"}  # full canvas size

POST <base>/denoise
  {"image": "<b64 png>", "strength": 1..100}   → {"image": "<b64 png>"}  # same size
```

A few lines of Flask wrap ComfyUI, a rembg/SAM script, or a cloud API
equally well. Wrong-size responses, timeouts, and unreachable servers are
reported cleanly, never crash.

## pip plugins
Publish a package exposing a `photoslop.modeladapter.ModelAdapter` subclass
under the **`photoslop.model_adapters`** entry-point group and it appears in
the backend picker automatically. Implement `capabilities()` and whichever of
`select_subject(image)` / `generative_fill(image, mask, prompt)` you support.
Broken plugins are skipped, never fatal.

## The features
- **Select → Subject (Model)**: your backend's mask becomes the live
  selection (thresholded at 50%).
- **Edit → Generative Fill… (Model)**: make a selection, type a prompt; the
  result composites through the standard selection plumbing (feather
  respected), one undo step.
