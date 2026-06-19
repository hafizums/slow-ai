# Architecture

## Architecture style

`slow_ai` is a modular monolith inside Frappe.

## High-level architecture

```txt
Canvas UI
↓
Frappe API methods
↓
Application services
↓
Domain rules
↓
Workflow engine
↓
Node registry
↓
Provider adapter
↓
External API provider
↓
AI Asset / AI Provider Job / AI Credit Ledger
```

## Required layers

```txt
api/
application/
domain/
engine/
node_registry/
providers/
infrastructure/
workers/
doctype/
tests/
```

## Layer responsibilities

### api/

Frappe whitelisted methods only.

Allowed:

```txt
Validate request shape
Call application service
Return safe response
```

Forbidden:

```txt
Provider calls
Workflow graph execution
Business rules
Direct asset writing
Cost ledger logic
```

### application/

Use-case orchestration.

Allowed:

```txt
Start workflow run
Save workflow
Create workflow snapshot
Coordinate repositories
Call domain validation
Enqueue workers
Enforce permissions
```

### domain/

Pure business rules.

Allowed:

```txt
Graph validation
Snapshot rules
Status policies
Cost policies
Node/provider contracts
Permission rules
```

### engine/

Workflow execution core.

Allowed:

```txt
DAG execution
Dependency resolution
Node run state transitions
Input/output propagation
Failure handling
Retry/resume coordination
```

### node_registry/

Node definitions and schemas.

Allowed:

```txt
Node metadata
Input schema
Config schema
Output schema
Node execution logic
Node-specific validation
```

### providers/

External API provider adapters.

Allowed:

```txt
Provider authentication
Submit job
Poll job
Cancel job
Normalize response
Estimate cost
Provider-specific errors
```

### infrastructure/

Frappe-specific adapters.

Allowed:

```txt
Repositories
File storage
Queue helpers
Realtime event publishing
Secret access
```

### workers/

Long-running jobs.

Allowed:

```txt
Run workflow
Run node
Poll provider job
Resume workflow
Cancel workflow
Cleanup failed runs
```

### doctype/

Persistence only.

Allowed:

```txt
Schema
Relationships
Light field validation
Permissions
```

DocType controllers must not execute workflows or call providers.

## Core run flow

```txt
1. User saves workflow draft.
2. User starts run.
3. API calls RunService.start_run().
4. RunService validates graph.
5. RunService checks provider spend/model/account preflight.
6. RunService creates AI Workflow Version immutable snapshot.
7. RunService creates AI Workflow Run.
8. RunService creates AI Node Run records.
9. RunService enqueues worker.
10. Worker loads run and version.
11. Engine resolves DAG order.
12. Engine executes ready nodes through NodeDefinition.
13. Provider nodes call ProviderAdapter.
14. ProviderAdapter creates and updates AI Provider Job.
15. Outputs become AI Asset records.
16. Costs become AI Credit Ledger records.
17. Realtime events update UI.
18. Run history is persisted.
```

## Future extension rule

New node types must be addable by adding files under `node_registry/nodes/` without editing engine core.

New providers must be addable under `providers/<provider_name>/` without changing engine core.

## Task 04 engine core implementation

```txt
application/run_service.py
  validates workflow draft
  creates immutable AI Workflow Version
  creates AI Workflow Run
  creates AI Node Run records

infrastructure/repositories.py
  reads/writes Frappe DocTypes

engine/executor.py
  resolves DAG order
  propagates node outputs to downstream inputs
  persists workflow success/failure

engine/node_runner.py
  executes one NodeDefinition
  persists AI Node Run input/output/error state
```

The engine does not call providers directly and does not execute editable
workflow drafts.

## Task 12 review and hardening gate

Architecture boundaries are enforced by a real integration test:

```txt
slow_ai/tests/integration/test_architecture_boundaries.py
```

The gate checks that:

```txt
api/ methods remain thin Frappe whitelist delegates to application services
doctype/ controllers remain persistence-only
client assets call only approved slow_ai API methods
client assets do not contain provider credentials or provider execution logic
production code does not introduce local model runtime terms
production code does not reference ComfyUI source/runtime concepts
slow_ai layers do not use direct SQL
```

New APIs, canvas calls, or layer exceptions must update the test and the
contract docs in the same change. Exceptions must be narrow and documented.

## Task 09 asset and ledger pipeline

Provider output materialization lives in infrastructure services:

```txt
slow_ai/infrastructure/provider_outputs.py
  AssetWriter
  CreditLedgerService
  ProviderOutputService
```

Provider nodes and provider polling workers call `ProviderOutputService` after a
normalized provider result reaches `SUCCEEDED`. The service creates or reuses
`AI Asset` records linked to the `AI Workflow Run`, `AI Node Run`, and
`AI Provider Job`, then creates or reuses an `AI Credit Ledger` `DEBIT` record
when the provider result has a non-zero cost.

The service is idempotent by persisted source links. Re-polling a completed
provider job must not duplicate assets or ledger rows.

## Task 10 canvas placeholder

The first canvas surface is a Frappe Desk Page:

```txt
slow_ai/slow_ai/page/slow_ai_canvas/
```

The page is an editor and monitor only. It renders workflow draft nodes/edges,
calls existing whitelisted API methods, and subscribes to realtime events. It
does not import engine, provider, or node registry modules; it does not call
external providers; and it does not execute workflow graphs in the browser.

## Task 11 tool mode foundation

Tool mode adds a node-registry output marker and template application APIs:

```txt
slow_ai/node_registry/nodes/tool_output.py
slow_ai/application/templates.py
slow_ai/api/templates.py
```

`tool_output` is an output node. It packages connected inputs into persisted
`AI Node Run.output_json` for tool-style consumers, without calling providers or
writing assets/ledger rows itself.

`AI Workflow Template` APIs validate reusable workflow graphs and persist
template JSON. Creating a workflow from a template creates an editable
`AI Workflow` draft only. It does not execute the draft or enqueue workers.

## Task 05 provider implementation

```txt
providers/contracts.py
  defines ProviderJobRequest, ProviderSubmission, ProviderAdapter, and normalized provider result contracts

providers/registry.py
  registers WaveSpeed and Replicate through create_default_provider_registry()

providers/wavespeed/
  keeps WaveSpeed auth, REST client, adapter, response normalization, constants, and errors isolated

providers/replicate/
  keeps Replicate auth, REST client, adapter, response normalization, constants, and errors isolated

infrastructure/provider_jobs.py
  persists provider job request/response JSON, external job IDs, errors, costs, and lifecycle timestamps
```

WaveSpeed submission uses the server-side provider account secret or
`WAVESPEED_API_KEY`. The adapter creates `AI Provider Job` before any outbound
provider request and persists submit/poll results through the generic provider
job repository.

## Task 06 provider node implementation

```txt
node_registry/nodes/provider.py
  defines generic provider_text_to_image, provider_image_to_image,
  provider_image_to_video, provider_start_end_to_video, and
  provider_text_to_speech nodes

infrastructure/provider_outputs.py
  creates generated AI Asset records and non-zero AI Credit Ledger debits

engine/node_runner.py
  passes configured input-port values into NodeDefinition execution and persists
  returned provider_job links on AI Node Run
```

Provider nodes remain generic. They select a provider adapter through
`ProviderRegistry`; they do not import WaveSpeed internals, call provider HTTP
clients directly, or alter workflow drafts.

## Task 07 API implementation

```txt
api/workflows.py
  exposes save_workflow and get_workflow

api/runs.py
  exposes start_run, get_run_status, and get_history

api/queue.py
  exposes get_queue_status

api/assets.py
  exposes upload and view

application/workflows.py
application/runs.py
application/queue.py
application/assets.py
  contain the corresponding use-case logic

infrastructure/queue.py
  wraps frappe.enqueue for workflow execution workers
```

`start_run` creates persisted run records and enqueues
`slow_ai.workers.run_workflow.run_workflow` after commit. It does not execute a
workflow inside the HTTP request.

## Task 08 workers and realtime

```txt
workers/run_workflow.py
workers/run_node.py
workers/poll_provider_job.py
workers/resume_workflow.py
  execute persisted workflow, node, and provider job work outside HTTP requests

infrastructure/realtime.py
  publishes workflow, node, and provider job update events through Frappe realtime

engine/executor.py
  supports resume by skipping succeeded nodes and reusing persisted node outputs
```

Realtime events are emitted after DB updates. Clients must treat realtime as a
notification and reload status/history from the API when they need authoritative
state.
