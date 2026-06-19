# Project Brief

## Product name

`slow_ai`

## Product type

Frappe-native AI workflow platform.

## Inspiration

ComfyUI-style node workflows and Weave-like creative workflow UX.

## Implementation boundary

Use ComfyUI as a reference only.

Do not copy:

```txt
ComfyUI source code
ComfyUI frontend implementation
ComfyUI custom node implementations
ComfyUI exact UI/UX
ComfyUI branding
```

## Product goal

Build a visual AI workflow builder that executes external API provider jobs instead of local models.

## First provider

WaveSpeed.

## Runtime policy

API-provider-only.

No local GPU.  
No local checkpoints.  
No local model inference.  
No tensor-heavy local pipeline.
