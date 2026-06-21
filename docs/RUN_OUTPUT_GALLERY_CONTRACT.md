# Run Output Gallery Contract

## Purpose

The Run Output Gallery is the reusable read-only output layer for Tool Runs. It
lets `/app/slow-ai-tools` and shared run pages display generated or selected
`AI Asset` outputs without exposing provider internals or creating any
execution side effects.

## Application Service

```txt
slow_ai.application.run_outputs.get_run_output_gallery(
    workflow_run,
    selected_assets=None,
    include_unselected=True,
)
```

Normal run views must enforce project view access. Shared-link reads may reuse
the service only after `AI Tool Run Share` token/status/expiry checks, and must
pass the assets stored on `selected_assets_json` with unselected outputs
excluded.
Share creation must validate that every selected asset belongs to the workflow
run being shared. Public tool input assets and rerun asset edits must resolve
through the same project-scoped asset view path so inaccessible assets from
another project cannot be written into a tool draft.

## Public API

```txt
slow_ai.api.public_tools.get_run_output_gallery
```

This API requires a logged-in user and project view access. It is a thin
delegate to the application service through `slow_ai.application.public_tools`.
There is no guest gallery API for arbitrary runs.

The guest shared page continues to call only:

```txt
slow_ai.api.public_tools.get_shared_run
```

`get_shared_run` may internally reuse the gallery service, but it must return
only assets explicitly selected on the share record. Shared responses must also
strip project and workflow draft identifiers from the nested gallery `run`
metadata.

## Payload Shape

```txt
run:
  workflow_run
  workflow
  workflow_title
  project
  status
  queued_at
  started_at
  completed_at
  created
  modified
groups[]:
  group_id
  label
  source_node_run
  source_node_id
  source_node_type
  assets[]
assets[]:
  name
  asset_type
  mime_type
  file
  url
  width
  height
  duration_seconds
  source_workflow_run
  source_node_run
  source_provider_job
  source_output
  created
  modified
  metadata
  selected
  shareable
selected_assets[]
```

Asset preview URLs/files must come from the backend asset view application
service. The browser must not reconstruct output assets from raw run history or
node output JSON.

## Allowed UI Behavior

`/app/slow-ai-tools` may render:

```txt
grouped output sections
image/video/audio/text/JSON preview cards
safe asset metadata
Open Asset
Copy URL
Select for Share
Select All
Clear Selection
client-side asset type filters
```

The shared page may render only read-only selected output assets and safe run
metadata. It must not show any run, rerun, edit, provider, or account controls.

## Forbidden

The gallery service, public API, Tool Run page, and shared page must not:

```txt
call providers
start runs
enqueue workers
create AI Workflow Version
create AI Workflow Run
create AI Node Run
create AI Provider Job
create AI Asset
create AI Credit Ledger
expose provider account names
expose provider secrets
expose raw provider request_json
expose raw provider response_json
expose raw provider error JSON
expose workflow draft internals
render raw provider output URLs unless materialized as safe AI Asset view data
execute workflow logic in JavaScript
allow anonymous paid runs
```

## Tests

Required coverage lives in real Frappe integration tests and browser E2E:

```txt
safe grouped gallery payload for completed runs
failed/empty runs return safe empty payload
normal users scoped by project membership
VIEWER and EDITOR can view accessible galleries
nonmembers are rejected
gallery read creates no ProviderJob, Asset, Ledger, Workflow Version, Run, or Node Run
shared reads expose only selected assets
client assets contain no provider calls, secrets, account names, or raw provider payloads
```
