# Canvas UI Contract

## Purpose

The canvas UI is an editor and run monitor for persisted `slow_ai` workflows.

It must not execute workflows, call providers, or contain node/provider business
logic.

## Allowed UI actions

```txt
Render workflow draft nodes, edges, and layout
Call whitelisted slow_ai API methods
Save editable AI Workflow drafts
Start runs through the run API
Read queue, status, and history through APIs
Subscribe to Frappe realtime events
Render AI Asset, AI Provider Job, and AI Credit Ledger summaries from API data
```

## Forbidden UI actions

```txt
Call provider APIs directly
Read provider account secrets
Import engine, provider, or node registry code
Execute workflow graphs in the browser
Execute editable workflow drafts directly
Create AI Provider Job records directly
Create AI Asset or AI Credit Ledger rows directly
Copy ComfyUI source code, UI code, assets, or branding
Implement local model loading or inference
```

## Task 10 implementation

The initial Desk Page lives in:

```txt
slow_ai/slow_ai/page/slow_ai_canvas/
```

The page route is:

```txt
/app/slow-ai-canvas
```

The private Desk workspace is maintained by:

```txt
slow_ai/infrastructure/workspace.py
```

It creates or updates a private `Workspace` for each enabled system user on
install, migrate, and login. The workspace is navigation-only: it links to the
Slow AI canvas page and persisted DocTypes, but it must not call providers,
execute workflows, expose provider secrets, or contain engine logic.

Every permanent Slow AI DocType must have a navigation link in this workspace.
Add workspace charts only when the DocType has an admin-relevant aggregate or
operational KPI; otherwise leave charts empty so the workspace remains
navigation-only.

The canvas may use these whitelisted APIs:

```txt
slow_ai.api.nodes.get_object_info
slow_ai.api.workflows.get_workflow
slow_ai.api.workflows.save_workflow
slow_ai.api.runs.start_run
slow_ai.api.runs.get_run_status
slow_ai.api.runs.get_history
slow_ai.api.runs.get_run_timeline
slow_ai.api.queue.get_queue_status
slow_ai.api.assets.upload
slow_ai.api.assets.view
slow_ai.api.models.get_model_metadata
slow_ai.api.models.list_models
slow_ai.api.models.get_model
slow_ai.api.models.update_model_status
slow_ai.api.models.update_model_pricing
slow_ai.api.provider_accounts.list_accounts
slow_ai.api.provider_accounts.get_account
slow_ai.api.provider_accounts.create_account
slow_ai.api.provider_accounts.set_default
slow_ai.api.provider_accounts.disable_account
slow_ai.api.templates.list_templates
slow_ai.api.templates.get_template
slow_ai.api.templates.save_template
slow_ai.api.templates.create_workflow_from_template
slow_ai.api.templates.submit_template_for_review
slow_ai.api.templates.approve_template
slow_ai.api.templates.reject_template
slow_ai.api.templates.archive_template
slow_ai.api.templates.list_template_versions
slow_ai.api.templates.rollback_template_to_version
```

The Canvas page does not implement project membership management in the current
contract. It must not call `slow_ai.api.projects.list_members`,
`slow_ai.api.projects.add_member`, `slow_ai.api.projects.update_member_role`, or
`slow_ai.api.projects.disable_member` unless this contract and the architecture
boundary tests are updated.

Realtime subscriptions:

```txt
slow_ai_workflow_run_update
slow_ai_node_run_update
slow_ai_provider_job_update
```

The page is intentionally a placeholder. It provides a functional draft canvas
with a starter `text_prompt -> provider_text_to_image -> export_output` graph,
node palette, run monitor, queue summary, asset output panel, status polling
fallback, and realtime refresh hook without adding provider calls, local model
runtime, or workflow execution in client JavaScript.

The node palette is metadata-driven from `slow_ai.api.nodes.get_object_info`.
It renders these palette categories:

```txt
input
provider
image
video
audio
utility
output
```

Each node card shows label, type, category, input schema summary, config schema
summary, output schema summary, and an `Add Node` action. `Add Node` appends a
node object to the editable draft JSON using metadata defaults when present; it
does not execute workflow logic, create provider jobs, or call providers.

The graph editor is metadata-driven and rendered as a visual node canvas. It
uses the Frappe Desk page's native JavaScript/SVG layer as the maintainable
graph UI surface so the app does not require a separate execution path or
frontend business-logic bundle. It supports:

```txt
selecting draft nodes
dragging nodes to update draft layout positions
editing node config fields generated from object_info config_schema
editing node x/y layout positions
adding edges visually between compatible object_info ports
adding edges from the inspector between compatible object_info ports
deleting edges visually or from the inspector
deleting nodes and their incident edges
showing draft warnings from object_info metadata
```

Client-side draft warnings are advisory only. Backend graph validation in
`slow_ai.api.workflows.save_workflow` and backend run preflight before
`slow_ai.api.runs.start_run` remain the source of truth. The browser must not
validate by importing node registry, engine, provider adapter, worker, or DB
code. Dragging nodes and connecting/deleting edges must mutate editable draft
JSON only; persistence happens only when the user saves through
`slow_ai.api.workflows.save_workflow`.

The run monitor renders persisted execution state only. It reads workflow and
node status from `slow_ai.api.runs.get_run_status`, then reads provider jobs,
assets, ledger entries, and detailed run history from
`slow_ai.api.runs.get_history`. The run timeline must be rendered from
`slow_ai.api.runs.get_run_timeline`.

Both run APIs return safe display payloads only. The canvas must not depend on
raw provider request/response/error JSON, provider account names, raw provider
URLs, raw node input/output JSON, asset URLs/files from history, or arbitrary
asset metadata. Asset preview links must continue to come from
`slow_ai.api.assets.view`.

The monitor sections are:

```txt
workflow status
per-node status
provider job status
generated asset output
credit ledger and cost summary
safe error messages
run timeline
```

The timeline is derived from persisted run, node, provider job, and asset rows.
The backend timeline payload is safe and may show:

```txt
event timestamp
event title and message
status
node id and node type
safe amount and currency
```

Timeline UI states must remain explicit:

```txt
Loading timeline
No timeline events
Timeline unavailable
No timeline events match these filters
rendered safe event rows
```

If `slow_ai.api.runs.get_run_timeline` fails, the canvas must render only a
generic safe message such as `Timeline unavailable`. It must not render raw
exception text, server response JSON, stack traces, provider account names,
provider secrets, raw provider URLs, `request_json`, `response_json`,
`raw_error_json`, API keys, Authorization headers, or workflow draft internals.
Timeline rows must not be derived from `slow_ai.api.runs.get_history`.
When the selected run changes while a timeline request is in flight, stale
responses must not overwrite the currently selected run's timeline panel.
The Canvas may provide client-side timeline search and filters for event type,
status, and node id. These filters must operate only on the loaded safe
`get_run_timeline` events in browser memory, must escape rendered values, must
not issue provider calls, and must not reconstruct timeline rows from
`get_history`. Clear filters must restore the loaded safe events without
another provider call.

The UI must only display sanitized error messages. It must not render raw
provider responses, raw provider error JSON, provider account secrets, provider
adapter internals, engine calls, worker calls, DB calls, or provider URLs.
Asset links may only come from `slow_ai.api.assets.view`.

The asset output panel renders preview cards from run history asset names and
`slow_ai.api.assets.view` payloads only. Supported preview modes:

```txt
IMAGE: image thumbnail
VIDEO: video player when a safe asset URL/file is available
AUDIO: audio player when a safe asset URL/file is available
JSON: formatted metadata summary
TEXT: formatted metadata summary
```

Each card must show asset name, asset type, MIME type, source workflow run,
source node run, source provider job, dimensions, duration, created timestamp,
and modified timestamp when those values exist. The asset panel may provide
Open Asset, Copy URL, and Refresh Asset controls, but those controls must use
only the URL or file reference returned by `slow_ai.api.assets.view`.
Canvas asset previews must treat `assets.view` as a safe display API only:
sensitive asset metadata keys and raw provider URLs/secrets are removed or
redacted by the backend shared safe-payload utility before rendering.

Opening or refreshing Canvas run detail, history, timeline, and asset views must
not create, delete, enqueue, or mutate workflow versions, workflow runs, node
runs, provider jobs, assets, ledger rows, or share records.

The template library panel renders persisted `AI Workflow Template` summaries
from `slow_ai.api.templates.list_templates`. The panel may load a template
preview through `slow_ai.api.templates.get_template`, save the current editable
draft graph as a `DRAFT` template through `slow_ai.api.templates.save_template`,
and create an editable `AI Workflow` draft through
`slow_ai.api.templates.create_workflow_from_template`. It may also submit,
approve, reject, and archive templates through the template review APIs.

Template save, create, and review actions must not start runs, create immutable
workflow versions, enqueue workers, call providers, create provider jobs, create
assets, create ledger rows, or execute workflow logic in the browser. Template
previews may display template metadata, review status, node summaries, edge
counts, and preview asset names. Any rendered asset link or media preview must
still come from `slow_ai.api.assets.view`.

Internal template APIs are owner/System Manager surfaces. System Managers may
list, view, instantiate, review, archive, and rollback templates according to
the review lifecycle. Normal users may list/view/save/instantiate only templates
they own, and may submit only their own eligible templates for review. The
public Tool page must use `slow_ai.api.public_tools.*` for published runnable
templates instead of these internal template APIs.

The Save Template prompt must not offer direct `PUBLISHED`, `IN_REVIEW`, or
`ARCHIVED` statuses. Publishing, rejection, and archiving must stay behind the
dedicated review buttons and backend review APIs.

Approved templates have immutable published versions. The template preview panel
may call `slow_ai.api.templates.list_template_versions` to show version number,
status, snapshot hash, approval metadata, and the active published version.
Rollback must call only `slow_ai.api.templates.rollback_template_to_version`.
Rollback is an admin lifecycle action that creates a new ACTIVE immutable
version from a selected historical version; it must not start runs, enqueue
workers, create provider jobs, or execute workflow logic in the browser.

The Tool Mode panel provides a simplified form over an `AI Workflow Template`
without exposing the user to direct node editing. It may:

```txt
select a template from slow_ai.api.templates.list_templates
load template metadata through slow_ai.api.templates.get_template
render text_prompt fields as text inputs
render upload_asset fields as AI Asset name placeholders
upload a file or provide a URL/file reference, then create AI Asset records through slow_ai.api.assets.upload
preview selected/uploaded AI Assets through slow_ai.api.assets.view
display provider/model/config metadata as read-only text
create an editable AI Workflow draft from the selected template
apply form values to draft node config JSON
save the draft through slow_ai.api.workflows.save_workflow
start the saved draft only through slow_ai.api.runs.start_run
```

Tool Mode must not load templates by calling providers, submit form data to
providers, execute workflow logic in the browser, create provider jobs directly,
or create a separate execution path. Provider-node confirmation and backend run
preflight remain mandatory before paid provider runs.

For `upload_asset` nodes, Tool Mode may accept an existing `AI Asset` name,
upload a file through Frappe's file uploader, or create a new `AI Asset` from a
URL/file reference through `slow_ai.api.assets.upload`. The final `AI Asset`
record must be created through `slow_ai.api.assets.upload`. The
selected/uploaded asset name is written into the editable workflow draft node
config before save. Preview media and links must come only from
`slow_ai.api.assets.view`.

Provider-node drafts must require explicit confirmation before calling
`slow_ai.api.runs.start_run`. The confirmation must state:

```txt
This workflow may call an external provider and spend credits.
```

It must display each selected provider/model from node config and safe model
pricing metadata from `slow_ai.api.models.get_model_metadata` when available.
When pricing is unavailable, it must display `cost unknown`. The UI must never
read provider account secrets or call provider URLs.

The Provider Accounts panel may create, list, view, set default, and disable
BYOK provider accounts through `slow_ai.api.provider_accounts.*` only. It may
display safe metadata:

```txt
provider
account label
status
default flag
project scope
user scope
created timestamp
modified timestamp
```

The create form may accept an API key in a password input, but the key must be
cleared after save and must never be rendered from API responses. The panel must
not test keys, call provider URLs, display provider secrets, create provider
jobs, start runs, or bypass backend run preflight.
The backend provider-account policy is authoritative. The panel may display
safe backend rejection messages, but it must not expose API keys, Password
field values, raw provider payloads, provider URLs, or account secrets after
create/list/view/default/disable actions.

The Model Catalog panel may list, filter, inspect, and administer persisted
`AI Model` records through `slow_ai.api.models.*` only. Model reads are safe
metadata reads; model status, pricing, and metadata mutations are System
Manager-only. The panel may display safe
metadata:

```txt
provider
model_id
model_slug
display/model name
status
node_type
category
modality
parsed pricing summary
sanitized capabilities summary
sanitized input metadata summary
sanitized output metadata summary
```

Supported filters are provider, status, node_type, and category. Detail views
must use `slow_ai.api.models.get_model`. Admin actions may update model status
and pricing through the model admin APIs, but the client must not duplicate
pricing parser rules, read raw provider account data, render provider secrets or
raw provider URLs embedded in metadata, call provider URLs, create provider
jobs, start runs, or bypass backend run preflight. Disabled models and models
with unknown pricing must show clear warnings because backend preflight remains
the final model/pricing/balance guard.

## Browser E2E contract

Browser E2E coverage for the current placeholder canvas lives in:

```txt
apps/slow_ai/e2e/slow_ai_canvas.spec.js
```

It must use a real Frappe browser session and real persisted documents. It may
create fixtures through `slow_ai.tests.e2e.fixtures.setup_canvas_e2e`, then
drive `/app/slow-ai-canvas` to verify object_info palette loading, draft
node/config edits, visual node dragging, visual edge delete/create,
workflow saving with persisted layout, provider confirmation, run
status/history rendering, asset preview rendering, template listing, Model
Catalog list/detail/warning rendering, Provider Account
create/list/view/default/disable flows, Tool Mode template loading, Tool Mode
form persistence, and Tool Mode AI Asset select/create flows.

The browser E2E suite must not mock provider success, call providers directly,
expose provider secrets, execute workflow logic in client JavaScript, or use a
separate Tool Mode execution path. Paid provider execution remains covered only
by the gated real provider tests.
