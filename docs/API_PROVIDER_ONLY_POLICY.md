# API Provider Only Policy

## Core rule

`slow_ai` does not run AI models locally.

All generation must go through provider adapters.

```txt
Node
→ ProviderAdapter
→ External API provider
→ Provider job
→ Provider output
→ AI Asset
```

## Allowed execution types

```txt
External API text-to-image
External API image-to-image
External API image-to-video
External API start-end-to-video
External API text-to-video
External API text-to-speech
External API speech-to-text
External API background removal
External API upscaling
Server-side file stitching using normal media tools
Server-side asset download/upload
```

## Not allowed

```txt
Local diffusion inference
Local checkpoint loading
Local GPU model execution
Local LoRA loading
Local KSampler equivalent
Local model folder scanning
Local tensor graph execution
```

## Data type policy

Core types:

```txt
TEXT
IMAGE_ASSET
VIDEO_ASSET
AUDIO_ASSET
MASK_ASSET
JSON
NUMBER
BOOLEAN
```

Every media value should point to an `AI Asset`, not an in-memory tensor.

## Provider invariant

Create `AI Provider Job` before making an external API call.

## Asset invariant

Every generated file must become an `AI Asset`.
