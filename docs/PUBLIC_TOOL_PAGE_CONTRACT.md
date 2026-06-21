# Public Tool Page Contract

## Purpose

`/app/slow-ai-tools` lets logged-in users run published `AI Workflow Template`
records through a simplified form. It is a user-facing Tool Mode page, not an
admin graph editor.

The page reuses the existing backend execution path:

```txt
published AI Workflow Template
-> active immutable AI Workflow Template Version
-> editable AI Workflow draft
-> slow_ai.api.public_tools.prepare_workflow_from_template
-> slow_ai.api.runs.start_run
-> run preflight and billing balance policy
-> worker execution
-> run history and safe asset views
```

## Allowed Client APIs

```txt
slow_ai.api.public_tools.list_templates
slow_ai.api.public_tools.get_template
slow_ai.api.public_tools.prepare_workflow_from_template
slow_ai.api.public_tools.prepare_rerun_from_run
slow_ai.api.public_tools.update_rerun_draft_values
slow_ai.api.public_tools.list_my_runs
slow_ai.api.public_tools.get_my_run
slow_ai.api.public_tools.get_run_output_gallery
slow_ai.api.public_tools.cancel_my_run
slow_ai.api.public_tools.archive_my_run
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
slow_ai.api.runs.start_run
slow_ai.api.runs.get_run_timeline
slow_ai.api.assets.upload
slow_ai.api.assets.view
slow_ai.api.billing.get_balance
slow_ai.api.models.get_model_metadata
slow_ai.api.projects.list_members
slow_ai.api.projects.add_member
slow_ai.api.projects.update_member_role
slow_ai.api.projects.disable_member
```

No other `slow_ai` API method may be called from this page without updating this
contract and the architecture boundary tests.

The public Tool page must not call
`slow_ai.api.public_tools.cleanup_stale_tool_drafts`. Stale draft cleanup is a
backend/admin maintenance operation only.

## Template Rules

Only `PUBLISHED` templates are listed or loaded. `DRAFT`, `IN_REVIEW`,
`REJECTED`, and `ARCHIVED` templates must be hidden from the list and rejected
by the public tool application service.

Public template list/detail payloads are served from the active immutable
`AI Workflow Template Version`, not from mutable `AI Workflow Template` JSON.
The payload may include safe version fields:

```txt
template_version
version_no
snapshot_hash
```

Editing a `PUBLISHED` template draft must not change public Tool Mode behavior
until the template is submitted and approved again, creating a new active
version. Rollback creates another new active version copied from a prior
approved snapshot.

Publishing templates is a controlled review workflow. Template owners may
submit their own `DRAFT` or `REJECTED` templates for review. System Managers may
approve `IN_REVIEW` templates, reject them with a reason, or archive templates.
Normal users may run published templates through the public page, but they must
not publish templates into the public catalog.

Template loading must not start a run, enqueue workers, call providers, create
provider jobs, or create immutable workflow versions.

Review, approval, rejection, and archive actions must also be metadata-only:
they may update `AI Workflow Template` review fields but must not create
`AI Workflow`, `AI Workflow Version`, `AI Workflow Run`, `AI Node Run`,
`AI Provider Job`, `AI Asset`, or `AI Credit Ledger` records, enqueue workers,
or call providers.

## Project And Permission Rules

The first version requires a logged-in Frappe Desk session. Anonymous paid runs
are not supported.

The user must select an `AI Project`. System Managers may run against any
project. Normal users may run only against projects they own or where they have
an ACTIVE `AI Project Member` role that allows the requested action.

Project access roles:

```txt
AI Project.owner: full project administration
OWNER: full project administration
EDITOR: edit workflows/assets, start runs, view runs, create shares
VIEWER: view workflows/assets/runs only
BILLING: view/manage billing and provider account settings only
System Manager: cross-project administration
```

The Project Members panel may call only the safe project membership APIs listed
above. Membership write controls must be shown only after the backend
`list_members` call succeeds for the selected project. Users without membership
management access must see a generic safe unavailable state; failed member
add/update/disable attempts must render generic safe status text and must not
display raw server/provider payloads.

## Run Rules

The page must:

```txt
submit typed form values through slow_ai.api.public_tools.prepare_workflow_from_template
create an editable workflow draft from a published template
start only through slow_ai.api.runs.start_run
show status/history through scoped public tool run APIs
show output previews through slow_ai.api.public_tools.get_run_output_gallery
cancel only through slow_ai.api.public_tools.cancel_my_run
```

When a template has `input_schema_json`, the form must render from that schema
and the backend prepare API is the source of truth for required fields, type
checks, select options, numeric bounds, asset type checks, and allowed target
node config fields. Templates without `input_schema_json` may use the legacy
node-derived controls, but submitted values still go through backend allow-list
validation before an editable draft is saved.

Provider-node templates must show an external-provider credit warning before
the run is submitted. The warning is advisory; server-side run preflight and
billing balance checks remain authoritative.

## Forbidden

```txt
provider calls in client JavaScript
provider URLs in client JavaScript
provider secrets in API payloads or client assets
provider adapter imports in client assets
workflow execution in client JavaScript
direct ProviderJob creation from the page
direct database access from the page
anonymous paid runs
local model runtime
```

## Output Rules

Run progress comes from:

```txt
slow_ai.api.public_tools.get_my_run
```

Run output gallery links and previews come from:

```txt
slow_ai.api.public_tools.get_run_output_gallery
```

The gallery payload is built server-side from persisted `AI Asset` rows and
safe node output asset references. The backend gallery service resolves preview
URLs/files through the asset view application service before returning safe
metadata to the client. The page may render only the safe URLs or file
references returned in that payload; it must not render raw provider output
URLs unless the backend has materialized them as safe `AI Asset` metadata.

Direct client calls to `slow_ai.api.assets.view` remain allowed for explicit
user-selected input asset preview/upload workflows. They must not be used to
recompute run output galleries from raw history in the browser.

If a public-tool run timeline is shown, it must come from
`slow_ai.api.runs.get_run_timeline` and may render only the safe event fields
documented in `RUN_ACTIVITY_TIMELINE_CONTRACT.md`. The guest shared-output page
must not show the internal run timeline in the first timeline milestone.
Authenticated timeline UI states must explicitly cover loading, empty,
successful, and failed timeline fetches. A failed timeline fetch must render
only a generic safe message such as `Timeline unavailable`; it must not render
raw exception text, server response JSON, stack traces, provider account names,
provider secrets, raw provider URLs, `request_json`, `response_json`,
`raw_error_json`, API keys, Authorization headers, or workflow draft internals.
The public Tool page must not derive timeline rows from history/gallery
payloads. If a user switches run detail while a timeline request is in flight,
stale timeline responses must not overwrite the currently selected run detail.
Authenticated run detail may provide client-side timeline search and filters
for event type, status, and node id. Filters must operate only on already
loaded safe `get_run_timeline` events, must escape rendered values, must not
call providers, and must not call `get_history` or gallery APIs to reconstruct
timeline rows. Clear filters must restore all loaded safe events without
another provider call. If filters match nothing, the UI may show
`No timeline events match these filters`. The guest shared-output page must not
show timeline filters.

The gallery supports grouped output sections, asset preview cards, Open Asset,
Copy URL, Select for Share, Select All, Clear Selection, and lightweight
client-side filtering by asset type. These actions must not mutate run state,
call providers, create provider jobs, create assets, or create ledger rows.

## Tool Run Library Rules

The My Runs panel uses:

```txt
slow_ai.api.public_tools.list_my_runs
slow_ai.api.public_tools.get_my_run
slow_ai.api.public_tools.get_run_output_gallery
```

System Managers may view all runs. Normal users may view only runs for projects
they own or where they have an ACTIVE membership role.

Run library payloads may include safe run ids, workflow titles, project names,
statuses, timestamps, provider status counts, ledger cost totals, and asset
names/source metadata. They must not include provider account names, provider
secrets, raw provider request/response/error JSON, raw provider output URLs, or
unsafe error payloads. Node output details in run detail payloads must be
reduced to safe summaries by the backend shared safe-payload utility and must
not return raw node output JSON.

Listing or viewing runs must not create provider jobs, enqueue work, call
providers, mutate workflow state, or create assets/ledger rows.

Archived runs are hidden from default My Runs listings. The backend
`include_archived` option may return archived runs only to callers with normal
run/project access. `get_my_run` may still open an archived run for users with
view access.

## Cancellation Rules

The My Runs detail view may show a Cancel action only when the selected run is
cancellable for the current user. Cancellable workflow statuses are:

```txt
QUEUED
RUNNING
WAITING_PROVIDER
```

Cancel must call only:

```txt
slow_ai.api.public_tools.cancel_my_run
```

The backend cancel service is authoritative. Only the run project owner,
OWNER, EDITOR, or System Manager may cancel. VIEWER and BILLING members must be
rejected. Cancellation marks the existing workflow run `CANCELLED`, marks
non-terminal node runs `CANCELLED`, and may mark local non-terminal provider
jobs `CANCELLED` without calling external provider cancel APIs.

Cancel must not create workflow versions, workflow runs, node runs, provider
jobs, assets, credit ledger rows, enqueue workers, execute workflow logic, or
call providers. Public cancel and run-detail payloads may show only a safe
cancellation message and must not expose provider account names, provider
secrets, raw provider request/response/error JSON, provider URLs, or raw
errors.

## Archive Rules

The My Runs detail view may show an Archive action only for terminal runs when
the current user has archive permission. The Archive button must call only:

```txt
slow_ai.api.public_tools.archive_my_run
```

The backend archive service is authoritative. Only the run project owner,
OWNER, EDITOR, or System Manager may archive. VIEWER and BILLING members must be
rejected.

Archiving hides a run from default My Runs results and records safe archive
metadata on the existing `AI Workflow Run`. It must not cancel or stop active
runs; active runs are rejected. It must not delete records, call providers,
enqueue workers, execute workflow logic, create workflow versions, workflow
runs, node runs, provider jobs, assets, credit ledger rows, or share rows.
Archiving must not mutate existing `AI Workflow Version`, `AI Node Run`,
`AI Provider Job`, `AI Asset`, `AI Credit Ledger`, or `AI Tool Run Share`
records.

Archive payloads may expose safe run status and archive metadata only. They
must not expose provider account names, provider secrets, raw provider
request/response/error JSON, provider URLs, or unsafe errors.

## Rerun Rules

The My Runs detail view may show a Rerun action only for runs that have valid
template-version lineage:

```txt
source_template
source_template_version
```

Rerun preparation must call only:

```txt
slow_ai.api.public_tools.prepare_rerun_from_run
```

The backend rerun service must create a new editable `AI Workflow` draft from
the recorded immutable `AI Workflow Template Version`, not from mutable current
template JSON. If the parent template has since been edited, re-approved,
rolled back, or archived, rerun must still use the source run's recorded
historical template version when that version snapshot remains valid.

Rerun prefill values may come only from declared backend-safe
`input_schema_json` fields by reading the previous workflow draft config at
those schema targets. Rerun preparation must not copy provider accounts,
provider secrets, raw provider payloads, raw errors, run history internals, node
run internals, ledger data, or arbitrary node config.

Rerun preparation creates only an editable workflow draft. It must not create
immutable workflow versions, workflow runs, node runs, provider jobs, assets,
credit ledger rows, enqueue workers, or call providers. Starting the rerun must
first persist any user edits through:

```txt
slow_ai.api.public_tools.update_rerun_draft_values
```

The rerun draft update API may update only schema-allowed fields on the
prepared rerun draft. For historical template versions without
`input_schema_json`, it may update only the existing legacy public tool
allow-list:

```txt
text_prompt.text
upload_asset.asset
upload_asset.asset_type
```

Unknown fields and provider/model/provider account/API key/raw request/raw
response/raw error fields must be rejected. Schema-based updates must use the
same backend `input_schema_json` validation as normal public tool preparation.
Legacy no-schema upload asset updates must resolve assets through the safe
asset view path and enforce project access.

Rerun draft updates must not create immutable workflow versions, workflow runs,
node runs, provider jobs, assets, credit ledger rows, enqueue workers, or call
providers. After the rerun draft has been updated, starting the rerun must still
go through:

```txt
slow_ai.api.runs.start_run
```

Backend run preflight and billing balance checks remain authoritative for the
rerun.

## Draft Cleanup Rules

Public tool preparation and rerun preparation mark their editable `AI Workflow`
drafts as temporary public tool drafts. The backend cleanup service may delete
only stale marked drafts that have no `AI Workflow Run` and no immutable
`AI Workflow Version`.

Cleanup may be invoked through the System Manager-only backend API:

```txt
slow_ai.api.public_tools.cleanup_stale_tool_drafts
```

The public Tool page must not call this API and must not directly delete
records. Cleanup must not delete or mutate workflow versions, runs, node runs,
provider jobs, assets, credit ledger rows, or tool run shares. It must not call
providers, enqueue workers, expose provider account names, expose provider
secrets, expose raw provider payloads, expose provider URLs, or return unsafe
errors.

## Tool Run Sharing Rules

The My Runs panel may create and disable read-only share links for completed
successful tool runs through:

```txt
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
```

Share creation requires a logged-in user with OWNER or EDITOR access to the run
project. VIEWER and BILLING members may read accessible runs but cannot create
share links. Share owners, project owners/OWNER members, and System Managers may
disable shares.

Users must select at least one output asset in My Runs detail before creating a
share link. Empty selection is rejected by the client for usability and by the
backend as the source of truth. There is no implicit share-all behavior.

Shared links point to:

```txt
/slow-ai/shared/<token>
```

The shared page is read-only and may call only:

```txt
slow_ai.api.public_tools.get_shared_run
```

The shared page must not show a Run button, call `start_run`, create workflows,
enqueue workers, create provider jobs, expose provider account names, expose
provider secrets, expose raw provider payloads, or expose workflow draft
internals. It must not expose project metadata through either the top-level
shared run payload or nested `output_gallery.run`. Output previews must come
only from backend-safe asset view data for the selected assets stored on the
share record. Reading a shared run must not create, delete, enqueue, or mutate
workflow versions, workflow runs, node runs, provider jobs, assets, ledger rows,
or share records.
