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
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
slow_ai.api.runs.start_run
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
unsafe error payloads.

Listing or viewing runs must not create provider jobs, enqueue work, call
providers, mutate workflow state, or create assets/ledger rows.

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
share record.
