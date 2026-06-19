# Node Contract

## Goal

Every node must follow one predictable contract.

The engine must not hardcode node types.

## NodeDefinition interface

```python
class NodeDefinition:
    type: str
    label: str
    category: str
    version: str
    is_output_node: bool = False

    def input_schema(self) -> dict:
        ...

    def config_schema(self) -> dict:
        ...

    def output_schema(self) -> dict:
        ...

    def validate_inputs(self, inputs: dict) -> None:
        ...

    def validate_config(self, config: dict) -> None:
        ...

    def execute(self, context, inputs: dict, config: dict):
        ...
```

## Initial node types

```txt
text_prompt
upload_asset
provider_text_to_image
provider_image_to_image
provider_image_to_video
provider_start_end_to_video
provider_text_to_speech
stitch_video
export_output
tool_output
```

Task 03 implements these initial non-provider nodes:

### text_prompt

```txt
config.text: TEXT, required
outputs.text: TEXT
```

### upload_asset

```txt
config.asset: AI Asset document name, required
config.asset_type: IMAGE | VIDEO | AUDIO | MASK, required
outputs.image: IMAGE_ASSET
outputs.video: VIDEO_ASSET
outputs.audio: AUDIO_ASSET
outputs.mask: MASK_ASSET
```

`upload_asset` passes an existing `AI Asset` reference through the graph. It does
not read local files or call providers.

### export_output

```txt
inputs.text: TEXT
inputs.image: IMAGE_ASSET
inputs.video: VIDEO_ASSET
inputs.audio: AUDIO_ASSET
inputs.mask: MASK_ASSET
inputs.json: JSON
```

`export_output` is an output node and must have at least one connected input.

### tool_output

```txt
inputs.text: TEXT
inputs.image: IMAGE_ASSET
inputs.video: VIDEO_ASSET
inputs.audio: AUDIO_ASSET
inputs.mask: MASK_ASSET
inputs.json: JSON
config.output_name: TEXT, required
config.description: TEXT, optional
config.schema: JSON object, optional
```

`tool_output` is an output node for tool-mode workflows. It must have at least
one connected input and persists a structured payload containing
`output_name`, `description`, `schema`, and connected `values` in
`AI Node Run.output_json`. It does not call providers, execute workflow logic, or
write assets/ledger rows.

## Provider node rule

Provider nodes must call ProviderAdapter through provider registry.

Task 06 implements these generic provider nodes:

### provider_text_to_image

```txt
inputs.prompt: TEXT, required
config.provider: TEXT, required
config.model: AI Model document name, required
config.provider_account: AI Provider Account document name, optional
config.parameters: JSON object, optional
outputs.image: IMAGE_ASSET
outputs.result: JSON
```

### provider_image_to_image

```txt
inputs.prompt: TEXT, required
inputs.image: IMAGE_ASSET, required
inputs.mask: MASK_ASSET, optional
outputs.image: IMAGE_ASSET
outputs.result: JSON
```

### provider_image_to_video

```txt
inputs.image: IMAGE_ASSET, required
inputs.prompt: TEXT, optional
outputs.video: VIDEO_ASSET
outputs.result: JSON
```

### provider_start_end_to_video

```txt
inputs.start_image: IMAGE_ASSET, required
inputs.end_image: IMAGE_ASSET, required
inputs.prompt: TEXT, optional
outputs.video: VIDEO_ASSET
outputs.result: JSON
```

### provider_text_to_speech

```txt
inputs.text: TEXT, required
outputs.audio: AUDIO_ASSET
outputs.result: JSON
```

Required provider inputs may be connected through edges or supplied directly in
node config using the same port name. Provider nodes create or reuse an
idempotent `AI Provider Job`, call the configured provider adapter through
`ProviderRegistry`, create `AI Asset` rows for normalized provider outputs, and
create an `AI Credit Ledger` debit when the provider result has a non-zero
`cost_usd`.

Provider nodes emit asset outputs only after a `SUCCEEDED` normalized provider
result. If the provider returns a non-terminal status, the node returns
`waiting_provider=True`; the engine persists the node as `WAITING_PROVIDER` and
returns the workflow to `WAITING_PROVIDER`.

Task 09 provider outputs are materialized by `ProviderOutputService`, both for
immediate provider success inside a provider node and for async provider success
inside `workers/poll_provider_job.py`. Materialization creates or reuses linked
`AI Asset` records and one provider `AI Credit Ledger` debit before the node is
marked `SUCCEEDED`.

## Forbidden node behavior

Nodes must not:

```txt
Call provider APIs without AI Provider Job
Write files without AI Asset
Store cost without AI Credit Ledger
Mutate workflow draft
Read canvas UI state
Call local model runtimes
Load checkpoints or GPU models
```

## Extension rule

A new node should be addable without editing engine core.

Task 03 implementation paths:

```txt
slow_ai/node_registry/contracts.py
slow_ai/node_registry/registry.py
slow_ai/node_registry/schema.py
slow_ai/node_registry/nodes/text_prompt.py
slow_ai/node_registry/nodes/upload_asset.py
slow_ai/node_registry/nodes/export_output.py
slow_ai/node_registry/nodes/tool_output.py
slow_ai/node_registry/nodes/provider.py
```
