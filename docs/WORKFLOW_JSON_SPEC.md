# Workflow JSON Spec

## Purpose

Define the `slow_ai` execution graph format.

The format is ComfyUI-inspired but Frappe-native and API-provider-only.

## Draft workflow JSON example

```json
{
  "nodes": [
    {
      "id": "prompt_1",
      "type": "text_prompt",
      "label": "Prompt",
      "position": {"x": 100, "y": 100},
      "config": {
        "text": "A cinematic Malaysian product ad"
      }
    },
    {
      "id": "t2i_1",
      "type": "provider_text_to_image",
      "label": "Generate Image",
      "position": {"x": 400, "y": 100},
      "config": {
        "provider": "wavespeed",
        "model": "example/text-to-image",
        "parameters": {
          "aspect_ratio": "9:16"
        }
      }
    },
    {
      "id": "output_1",
      "type": "export_output",
      "label": "Output",
      "position": {"x": 700, "y": 100},
      "config": {}
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "prompt_1",
      "source_port": "text",
      "target": "t2i_1",
      "target_port": "prompt"
    },
    {
      "id": "edge_2",
      "source": "t2i_1",
      "source_port": "image",
      "target": "output_1",
      "target_port": "image"
    }
  ]
}
```

## Node object

Required fields:

```txt
id
type
config
```

Optional fields:

```txt
label
position
metadata
```

## Edge object

Required fields:

```txt
id
source
source_port
target
target_port
```

## Port types

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

## Validation rules

```txt
All node ids are unique
All edge ids are unique
All edges reference existing nodes
All source ports exist
All target ports exist
Port types are compatible
No graph cycles
All required inputs are connected or configured
All node types exist in NODE_REGISTRY
All configs pass node schema
At least one output node exists
No disabled model is used
```

## Task 03 implementation

Workflow JSON parsing and validation live in:

```txt
slow_ai/domain/workflow_json.py
slow_ai/domain/graph_validator.py
```

Entry points:

```txt
parse_workflow_json(workflow_json)
validate_workflow_json(workflow_json, node_registry=None)
slow_ai.application.workflow_validation.validate_workflow(workflow_json)
```

Validation accepts either a Python mapping or a JSON string with `nodes` and
`edges` arrays. It rejects malformed node/edge objects before graph validation
runs.

## Task 06 provider nodes

Generic provider nodes accept provider-specific settings through
`config.parameters`. Additional config fields that are not part of the common
provider config are also copied into the provider payload, which allows provider
model parameters to evolve without changing the engine.

Required input ports can be supplied by an edge or by a config field with the
same name:

```json
{
  "id": "tts_1",
  "type": "provider_text_to_speech",
  "config": {
    "provider": "wavespeed",
    "model": "example/text-to-speech",
    "text": "Narration text"
  }
}
```

Provider node execution persists `AI Provider Job`, generated `AI Asset`, and
non-zero cost `AI Credit Ledger` records.

## Task 11 tool output and templates

Tool-mode workflows declare structured outputs with `tool_output` nodes:

```json
{
  "id": "tool_output_1",
  "type": "tool_output",
  "config": {
    "output_name": "answer",
    "description": "Primary response",
    "schema": {"type": "string"}
  }
}
```

`tool_output` accepts the same input value categories as `export_output`, but
stores the connected values under a named tool payload in node `output_json`.

`AI Workflow Template` stores reusable graph JSON with the same `nodes`,
`edges`, and `layout` shape. Template writes must pass normal workflow graph
validation before persistence.
