# Asset Contract

## Purpose

All media inputs and outputs must be represented as `AI Asset` records.

## AssetRef

```json
{
  "asset": "AI-ASSET-0001",
  "asset_type": "IMAGE",
  "url": "/files/example.png",
  "mime_type": "image/png",
  "metadata": {}
}
```

## Supported asset types

```txt
IMAGE
VIDEO
AUDIO
MASK
JSON
TEXT
```

## Asset creation rules

Create `AI Asset` when:

```txt
User uploads file
Provider returns generated file
Server stitches media output
Server transforms file
Workflow exports result
```

User-uploaded assets must be created only through
`slow_ai.api.assets.upload` / `slow_ai.application.assets.upload`, which require
project edit access (`AI Project.owner`, OWNER, EDITOR, or System Manager).
Each successful upload creates exactly one `AI Asset` and must not create
workflow versions, workflow runs, node runs, provider jobs, credit ledger rows,
tool-run shares, workers, or provider calls.

Asset preview reads must go through `slow_ai.api.assets.view` or a backend
service that delegates to the same safe asset view path. Authenticated view
requires project view access; Guest access to generated outputs is only through
validated share-token payloads from `slow_ai.api.public_tools.get_shared_run`.
Safe preview payloads may include name, type, file/url, MIME type, dimensions,
duration, source links, timestamps, and safe metadata. They must not expose
provider account names, provider secrets, raw provider URLs embedded in
metadata, raw request/response/error JSON, API keys, Authorization headers, or
workflow draft internals.

## Forbidden patterns

```txt
Provider output URL stored only in node output_json
Uploaded file used without AI Asset
Generated media written to File without AI Asset
Asset source not linked to node run/provider job
```

## Task 09 implementation

Asset creation is centralized in:

```txt
slow_ai/infrastructure/provider_outputs.py
  AssetWriter.create_uploaded_asset()
  AssetWriter.create_provider_assets()
  ProviderOutputService.materialize()
```

Rules:

```txt
Uploaded assets are created through AssetWriter.
Provider outputs are materialized only after normalized provider success.
Provider output assets must set source_workflow_run, source_node_run, and source_provider_job.
Provider output materialization is idempotent by source_provider_job.
Node output_json stores AI Asset document names, not raw provider URLs.
```

Provider output port mapping:

```txt
IMAGE -> image
VIDEO -> video
AUDIO -> audio
MASK  -> mask
JSON  -> json
TEXT  -> text
```
