# Tool Mode Contract

## Purpose

Tool mode lets a workflow behave like a reusable tool by declaring structured
outputs through `tool_output` nodes and by storing reusable graphs as
`AI Workflow Template` records.

Tool mode is still API-provider-only. It does not introduce browser execution,
local model runtime, or provider calls outside provider adapters.

## Tool Output Node

```txt
type: tool_output
category: tool
is_output_node: true
```

Inputs:

```txt
text: TEXT
image: IMAGE_ASSET
video: VIDEO_ASSET
audio: AUDIO_ASSET
mask: MASK_ASSET
json: JSON
```

Config:

```txt
output_name: TEXT, required
description: TEXT, optional
schema: JSON object, optional
```

Execution output:

```json
{
  "output_name": "answer",
  "description": "Primary tool response",
  "schema": {"type": "string"},
  "values": {"text": "Generated answer"}
}
```

Rules:

```txt
tool_output must have at least one connected input.
tool_output does not call providers.
tool_output does not write assets or ledger rows.
tool_output is persisted through normal AI Node Run output_json.
```

## Workflow Templates

`AI Workflow Template` stores reusable workflow JSON:

```txt
template_name
status
category
description
preview_asset
nodes_json
edges_json
layout_json
```

Template application services validate the graph before writing template JSON.
Creating a workflow from a template creates an editable `AI Workflow` draft only;
it does not create a workflow version, start a run, enqueue workers, or call
providers.

## API Methods

```txt
slow_ai.api.templates.save_template
slow_ai.api.templates.get_template
slow_ai.api.templates.list_templates
slow_ai.api.templates.create_workflow_from_template
```

Layer rule:

```txt
api/templates.py -> application/templates.py -> domain validation / DocType persistence
```

Forbidden:

```txt
Provider calls in template APIs
Workflow execution in template APIs
DocType controller business logic
Client-side provider calls
Local model loading or inference
```
