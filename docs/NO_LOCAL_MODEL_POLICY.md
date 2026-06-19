# No Local Model Policy

## Purpose

This project must remain API-provider-only.

## Forbidden modules

Do not implement:

```txt
checkpoint loader
CLIP loader
VAE loader
KSampler
sampler scheduler
CUDA memory manager
GPU device manager
model folder scanner
local model downloader
local LoRA loader
local inference runtime
tensor cache
```

## Forbidden dependencies

Do not add heavy local inference dependencies unless separately approved:

```txt
torch
torchvision
diffusers
transformers for local inference
xformers
accelerate for local inference
onnxruntime for local inference
cuda-specific packages
```

This does not forbid lightweight HTTP clients, media utilities, or SDKs used only for provider APIs.

## Review rule

Any PR that introduces local model dependencies is blocked unless the architecture direction changes.
