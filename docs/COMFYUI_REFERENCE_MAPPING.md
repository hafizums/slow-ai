# ComfyUI Reference Mapping

## Purpose

Map ComfyUI concepts to `slow_ai` concepts for architecture inspiration only.

Do not copy ComfyUI source code.

## Concept mapping

| ComfyUI concept | slow_ai concept |
|---|---|
| Workflow JSON | AI Workflow Version `nodes_json` and `edges_json` |
| Prompt API `/prompt` | `slow_ai.api.runs.start_run` |
| Prompt queue | Frappe background job queue |
| PromptExecutor | `engine/executor.py` |
| Node class | `NodeDefinition` |
| NODE_CLASS_MAPPINGS | `NODE_REGISTRY` |
| INPUT_TYPES | `input_schema` / `input_types()` |
| RETURN_TYPES | `output_schema` / `return_types()` |
| CATEGORY | node `category` |
| FUNCTION | node `execute()` |
| OUTPUT_NODE | `is_output_node` |
| IS_CHANGED | `input_hash`, `config_hash`, `cache_key` |
| Tool/output-mode workflow | `tool_output` node plus `AI Workflow Template` |
| `/object_info` | `slow_ai.api.nodes.get_object_info` |
| `/history/{prompt_id}` | `slow_ai.api.runs.get_history` |
| `/queue` | `slow_ai.api.queue.get_queue_status` |
| `/view` | `AI Asset` view/download API |
| `/ws` | `frappe.publish_realtime` |
| Custom nodes | `node_registry/nodes/*.py` |
| Workflow templates | `AI Workflow Template` |

## What to reuse conceptually

```txt
Graph-based workflow execution
Node metadata API
Node input/output schemas
Queue-based execution
Execution history
Output node
Reusable workflow/template mode
Tool-style output declaration
```

## What not to implement

```txt
CheckpointLoader
CLIPLoader
VAELoader
KSampler
CUDA memory management
Local model file scanner
Local diffusion pipeline
Tensor image processing core
```
