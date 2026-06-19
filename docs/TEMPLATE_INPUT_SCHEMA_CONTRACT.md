# Template Input Schema Contract

## Purpose

`AI Workflow Template.input_schema_json` defines the user-facing fields for
Tool Mode and `/app/slow-ai-tools`. It is safe metadata for collecting values;
it is not a workflow execution path.

## Shape

The stored value is a JSON list of input descriptors. Each descriptor must
include:

```txt
id
label
input_type
target_node_id
target_config_field
required
```

Supported `input_type` values:

```txt
TEXT
LONG_TEXT
NUMBER
SELECT
BOOLEAN
ASSET
IMAGE_ASSET
VIDEO_ASSET
AUDIO_ASSET
```

Optional safe metadata may include:

```txt
help
description
placeholder
example
default
options
min
max
accepted_asset_types
ui
```

`SELECT` inputs require explicit options. `NUMBER` inputs may define `min` and
`max`. Asset inputs validate real `AI Asset` records, allowed asset types, and
project access.

## Safety Rules

Template save validates that every target node exists and every target config
field already exists on that node config. The following target fields are never
allowed:

```txt
provider
model
provider_account
api_key
api_key_secret
request_json
response_json
raw_error_json
```

Fields containing `api_key` are also rejected.

The backend prepare service rejects missing required values, invalid select
options, out-of-range numbers, invalid booleans, inaccessible assets, wrong
asset types, unknown input ids, and unsafe target fields. The browser can render
schema hints, but backend validation remains authoritative.

## Public Tool Flow

`/app/slow-ai-tools` renders schema fields when `input_schema_json` is present.
On Run it calls:

```txt
slow_ai.api.public_tools.prepare_workflow_from_template
slow_ai.api.runs.start_run
```

`prepare_workflow_from_template` creates only an editable `AI Workflow` draft
after validating submitted values. It must not create workflow versions, runs,
node runs, provider jobs, assets, credit ledger rows, enqueue workers, execute
workflow logic, or call providers.

Templates without `input_schema_json` may use legacy node-derived controls for
`text_prompt` and `upload_asset`, but those values still go through a backend
allow-list before a draft is saved.

## Forbidden

```txt
provider calls from client JavaScript
provider URLs or provider secrets in schema payloads
provider account names in public pages
raw provider request/response/error JSON
workflow execution in client JavaScript
ProviderJob creation from template/schema/prepare APIs
anonymous paid runs
local model runtime
```
