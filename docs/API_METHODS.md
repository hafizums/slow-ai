# API Methods

## ComfyUI-inspired API equivalents

```txt
slow_ai.api.nodes.get_object_info
slow_ai.api.runs.start_run
slow_ai.api.runs.get_run_status
slow_ai.api.runs.get_history
slow_ai.api.runs.get_run_timeline
slow_ai.api.queue.get_queue_status
slow_ai.api.assets.upload
slow_ai.api.assets.view
slow_ai.api.billing.create_top_up
slow_ai.api.billing.get_balance
slow_ai.api.billing.get_ledger
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
slow_ai.api.projects.list_my_projects
slow_ai.api.projects.list_members
slow_ai.api.projects.add_member
slow_ai.api.projects.update_member_role
slow_ai.api.projects.disable_member
slow_ai.api.public_tools.list_templates
slow_ai.api.public_tools.get_template
slow_ai.api.public_tools.create_workflow_from_template
slow_ai.api.public_tools.prepare_workflow_from_template
slow_ai.api.public_tools.prepare_rerun_from_run
slow_ai.api.public_tools.update_rerun_draft_values
slow_ai.api.public_tools.cleanup_stale_tool_drafts
slow_ai.api.public_tools.list_my_runs
slow_ai.api.public_tools.get_my_run
slow_ai.api.public_tools.get_run_output_gallery
slow_ai.api.public_tools.cancel_my_run
slow_ai.api.public_tools.archive_my_run
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
slow_ai.api.public_tools.get_shared_run
slow_ai.api.workflows.save_workflow
slow_ai.api.workflows.get_workflow
slow_ai.api.templates.save_template
slow_ai.api.templates.get_template
slow_ai.api.templates.list_templates
slow_ai.api.templates.create_workflow_from_template
slow_ai.api.templates.submit_template_for_review
slow_ai.api.templates.approve_template
slow_ai.api.templates.reject_template
slow_ai.api.templates.archive_template
```

## start_run must

```txt
Call application service
Validate workflow
Create AI Workflow Version
Create AI Workflow Run
Create AI Node Run records
Enqueue worker
Return run id
```

## start_run must not

```txt
Execute provider job directly
Run whole workflow inside HTTP request
```

## get_object_info

```txt
Method: slow_ai.api.nodes.get_object_info
Layer rule: API delegates to slow_ai.application.node_catalog.get_object_info
Returns: registered node metadata and input/config/output schemas
```

`get_object_info` is metadata-only. It must not execute node logic, inspect
workflow drafts, call providers, or read local model folders.

## Implemented methods

### slow_ai.api.workflows.save_workflow

```txt
Arguments: project, title, nodes, edges, layout, workflow, status
Application service: slow_ai.application.workflows.save_workflow
Writes: AI Workflow draft JSON
Returns: persisted workflow draft payload
```

`save_workflow` validates the supplied graph through application/domain
workflow validation before writing the draft. It does not create an immutable
version or execute a run.

### slow_ai.api.workflows.get_workflow

```txt
Arguments: workflow
Application service: slow_ai.application.workflows.get_workflow
Returns: workflow draft with parsed nodes, edges, and layout
```

### slow_ai.api.runs.start_run

```txt
Arguments: workflow
Application service: slow_ai.application.runs.start_run
Writes: AI Workflow Version, AI Workflow Run, AI Node Run
Enqueues: slow_ai.workers.run_workflow.run_workflow
Returns: workflow_version, workflow_run, node_runs, queue_job_id
```

`start_run` must leave the `AI Workflow Run` in `QUEUED` state and must not call
`WorkflowExecutor` directly. Before creating the immutable workflow version or
enqueueing a worker, it runs server-side preflight policy through
`slow_ai.application.run_preflight`. Preflight covers provider-node
model/account/spend checks and persisted project/user/provider-account quota
checks.

If the same unchanged workflow draft is submitted again within the short
server-side idempotency window while a matching run is still `QUEUED`,
`RUNNING`, or `WAITING_PROVIDER`, `start_run` returns the existing immutable
workflow version, workflow run, and node run names instead of creating duplicate
records. A queued duplicate may re-enqueue the same workflow-run job id for
recovery. Terminal runs are not reused, so an intentional later rerun can create
a new immutable version/run through the same API.

Preflight rejection must happen before creating `AI Workflow Version`,
`AI Workflow Run`, `AI Node Run`, `AI Provider Job`, reservation ledger, asset,
or queue side effects for the attempted run. It must not call providers. Safe
quota rejection messages may be returned to Canvas or Public Tool callers, but
clients must not implement authoritative quota checks.

### slow_ai.api.runs.get_run_status

```txt
Arguments: workflow_run
Application service: slow_ai.application.runs.get_run_status
Returns: safe workflow run status plus safe node run summaries
```

`get_run_status` enforces project view access and may return only safe run
identity/status/timestamps, safe template lineage, safe node run summaries, and
a sanitized run error message. It must not expose raw error dictionaries,
provider secrets, provider account names, raw provider URLs, API keys,
Authorization headers, or workflow draft internals.

### slow_ai.api.runs.get_history

```txt
Arguments: workflow_run
Application service: slow_ai.application.runs.get_history
Returns: safe display history for run, node runs, provider jobs, assets, and ledger rows
```

`get_history` enforces project view access and returns display summaries only.
It must not return `provider_account`, `request_json`, `response_json`,
`raw_error_json`, `external_job_id`, raw provider URLs, provider secrets, API
keys, Authorization headers, workflow draft internals, raw node input JSON, raw
node output JSON, asset URLs/files, or arbitrary asset metadata. Node output is
reduced to a safe summary, provider errors are reduced to safe message/code
fields, and asset preview URLs/files must be loaded through
`slow_ai.api.assets.view`.

### slow_ai.api.runs.get_run_timeline

```txt
Arguments: workflow_run
Application service: slow_ai.application.runs.get_run_timeline
Returns: safe, ordered run activity timeline generated from persisted records
```

`get_run_timeline` enforces project view access and derives timeline events
from `AI Workflow Run`, `AI Node Run`, `AI Provider Job`, `AI Asset`,
`AI Credit Ledger`, and `AI Tool Run Share` records. It is read-only and must
not create workflow versions, workflow runs, node runs, provider jobs, assets,
ledger rows, shares, queue jobs, or provider calls.

The timeline payload may include safe event metadata such as timestamp, event
type, title/message, related DocType/name, node id/type, status, and safe
amount/currency. It must not expose provider account names, provider secrets,
raw provider request/response/error JSON, raw provider URLs, API keys, or
workflow draft internals.

### slow_ai.api.public_tools.prepare_rerun_from_run

```txt
Arguments: workflow_run, title
Application service: slow_ai.application.public_tools.prepare_rerun_from_run
Writes: AI Workflow draft only
Returns: new workflow draft, historical template-version metadata, safe prefilled input values, source run summary
```

`prepare_rerun_from_run` requires logged-in project edit access and valid
`source_template` / `source_template_version` lineage on the source run. It
loads the recorded immutable `AI Workflow Template Version`, not mutable current
template JSON, so current template edits, reapprovals, rollback, or archive do
not change the rerun draft source.

Prefill values are extracted only through declared `input_schema_json` target
fields from the previous workflow draft and are revalidated by the same backend
template input service before the new draft is saved.

The method must not call providers, enqueue workers, create `AI Workflow
Version`, `AI Workflow Run`, `AI Node Run`, `AI Provider Job`, `AI Asset`, or
`AI Credit Ledger` rows.

### slow_ai.api.public_tools.update_rerun_draft_values

```txt
Arguments: workflow, values
Application service: slow_ai.application.public_tools.update_rerun_draft_values
Writes: existing rerun AI Workflow draft JSON only
Returns: updated workflow draft payload
```

`update_rerun_draft_values` requires logged-in project edit access, a rerun
draft with valid template-version lineage, and no existing `AI Workflow Run` for
that workflow. It reloads the recorded immutable template version. When the
version has `input_schema_json`, submitted values are applied only through that
schema. Historical no-schema versions use the existing legacy public tool
allow-list only:

```txt
text_prompt.text
upload_asset.asset
upload_asset.asset_type
```

Unknown fields and unsafe targets such as provider, model, provider account,
API key, raw request, raw response, or raw error fields must be rejected by the
same backend template input validation used by
`prepare_workflow_from_template`. Legacy no-schema upload asset edits must
resolve through the safe asset view path and enforce project access.

The method must not call providers, enqueue workers, create `AI Workflow
Version`, `AI Workflow Run`, `AI Node Run`, `AI Provider Job`, `AI Asset`, or
`AI Credit Ledger` rows.

### slow_ai.api.queue.get_queue_status

```txt
Arguments: none
Application service: slow_ai.application.queue.get_queue_status
Returns: queued and running workflow run summaries
```

The queue status API uses persisted workflow run state as the source of truth.

### slow_ai.api.assets.upload

```txt
Arguments: project, asset_type, url, file, mime_type, metadata
Application service: slow_ai.application.assets.upload
Writes: AI Asset
Returns: asset view payload
```

The upload API records a provided file reference or URL as an `AI Asset`. It
does not call providers.

### slow_ai.api.assets.view

```txt
Arguments: asset
Application service: slow_ai.application.assets.view
Returns: safe AI Asset metadata, created/modified timestamps, source links, dimensions, duration, and URL/file reference
```

The returned URL/file reference is the only asset preview source the canvas may
render. The method must not return provider account secrets, provider adapter
internals, raw provider responses, or raw provider errors. Asset metadata is
returned only after sensitive metadata keys and unsafe provider URLs/secrets are
redacted or removed through `slow_ai.application.safe_payloads`; raw provider
payload metadata remains server-side only.

### slow_ai.api.billing.create_top_up

```txt
Arguments: project, amount_usd, description, reference_doctype, reference_name
Application service: slow_ai.application.billing.create_top_up
Writes: AI Credit Ledger CREDIT
Returns: safe ledger row and current project balance
```

`create_top_up` is an admin billing operation for project billing
administrators. It creates one append-only credit ledger row. Project owners,
OWNER members, BILLING members, and System Managers may create top-ups
according to the central project access policy. EDITOR, VIEWER, non-member, and
Guest users are rejected before ledger or execution side effects. It does not
call providers, create runs, enqueue workers, or expose provider secrets.

### slow_ai.api.billing.get_balance

```txt
Arguments: project, user
Application service: slow_ai.application.billing.get_balance
Returns: current credit, reserve, release, debit, adjustment, and balance totals
```

When `user` is omitted, balance is calculated for the project. When `user` is
provided, balance is calculated from ledger rows owned by that user within the
project. The API reads `AI Credit Ledger` only and does not call providers.
Available balance is calculated as `CREDIT + ADJUSTMENT + RELEASE - DEBIT -
RESERVE`.

### slow_ai.api.billing.get_ledger

```txt
Arguments: project, user, limit
Application service: slow_ai.application.billing.get_ledger
Returns: safe ledger rows plus current balance
```

The ledger API returns safe accounting fields only. It must not return provider
account secrets, raw provider responses, provider credentials, or provider
adapter internals.

Billing read/write APIs enforce `slow_ai.application.project_access` policy.
Project owners, OWNER members, BILLING members, and System Managers may read
balance/ledger data. EDITOR, VIEWER, non-member, Guest, and DISABLED members
are rejected without mutating ledger or execution records.

### slow_ai.api.models.get_model_metadata

```txt
Arguments: model_ids
Application service: slow_ai.application.models.get_model_metadata
Returns: public AI Model metadata and parsed pricing summary keyed by name, model_id, and model_slug
```

This method returns only safe model metadata for UI display. It is a read-only
metadata endpoint and does not require project membership. It must not return
provider account names or secrets, raw `pricing_json`, provider credentials,
raw provider URLs embedded in metadata, or provider internals, and it must not
call providers.

Safe returned fields include model identity, display name, provider, status,
modality, node type, category, parsed pricing summary, and sanitized
capabilities/input/output metadata.

### slow_ai.api.models.list_models

```txt
Arguments: provider, status, node_type, category
Application service: slow_ai.application.models.list_models
Returns: safe AI Model summaries
```

By default, `list_models` returns enabled models only. Passing `status=ALL`
returns enabled and disabled models for admin review. The method returns parsed
safe metadata only and never returns raw pricing JSON, provider credentials,
provider account names or secrets, raw provider URLs embedded in metadata, or
provider adapter internals.

### slow_ai.api.models.get_model

```txt
Arguments: model
Application service: slow_ai.application.models.get_model
Returns: safe AI Model detail resolved by name, model_id, or model_slug
```

The detail payload uses the same safe field contract as `get_model_metadata` and
does not call providers.

### slow_ai.api.models.update_model_status

```txt
Arguments: model, status
Application service: slow_ai.application.models.update_model_status
Writes: AI Model status
Returns: safe AI Model detail
```

This is a System Manager-only admin operation. It must not call providers, create
provider jobs, expose provider secrets, or return raw provider internals.

### slow_ai.api.models.update_model_pricing

```txt
Arguments: model, amount_usd, unit, currency
Application service: slow_ai.application.models.update_model_pricing
Writes: AI Model pricing_json
Returns: safe AI Model detail with parsed pricing summary
```

Pricing updates write the persisted model pricing JSON, then return the same
centralized safe parser output used by `get_model_metadata` and run preflight.
Blank `amount_usd` clears known pricing while preserving unit/currency metadata.
The API is System Manager-only. It must not call providers or duplicate
pricing-key parsing in the client.

### slow_ai.api.models.update_model_metadata

```txt
Arguments: model, capabilities, input_metadata, output_metadata
Application service: slow_ai.application.models.update_model_metadata
Writes: AI Model metadata JSON fields
Returns: safe AI Model detail
```

Metadata updates are System Manager-only and accept JSON objects or JSON
strings. Responses sanitize metadata and must not expose provider accounts,
provider secrets, raw provider URLs, or provider adapter internals.

### slow_ai.api.provider_accounts.list_accounts

```txt
Arguments: provider, project, user, include_disabled
Application service: slow_ai.application.provider_accounts.list_accounts
Returns: safe AI Provider Account summaries
```

Provider account list payloads include identity and scope metadata only:
provider, account label, status, default flag, project, user, owner, creation,
and modified timestamps. They never include API keys, Password fields, raw auth
data, provider URLs, or provider adapter internals, and they do not call
providers.

Project-scoped provider account reads and writes require provider-account
management access for the project: project owner, OWNER member, BILLING member,
or System Manager. EDITOR, VIEWER, non-member, Guest, and DISABLED members are
rejected without creating or mutating provider accounts or execution records.
Owning a project-scoped `AI Provider Account` row does not bypass disabled
membership or role policy.

### slow_ai.api.provider_accounts.get_account

```txt
Arguments: account
Application service: slow_ai.application.provider_accounts.get_account
Returns: one safe AI Provider Account summary
```

### slow_ai.api.provider_accounts.create_account

```txt
Arguments: provider, account_label, api_key, project, user, is_default, rate_limit
Application service: slow_ai.application.provider_accounts.create_account
Writes: AI Provider Account
Returns: safe AI Provider Account summary
```

`api_key` is written only to the `AI Provider Account.api_key_secret` Password
field. The return payload must not include the key or Password field value.
Creating an account must not call providers, create provider jobs, create runs,
or enqueue workers.
Allowed create operations create exactly one `AI Provider Account` row. Denied
create operations create no provider account, workflow, run, provider job,
asset, ledger, or share records.

### slow_ai.api.provider_accounts.set_default

```txt
Arguments: account
Application service: slow_ai.application.provider_accounts.set_default
Writes: AI Provider Account default flags within matching provider/project/user scope
Returns: safe AI Provider Account summary
```

### slow_ai.api.provider_accounts.disable_account

```txt
Arguments: account
Application service: slow_ai.application.provider_accounts.disable_account
Writes: AI Provider Account status
Returns: safe AI Provider Account summary
```

Disabling an account clears its default flag. Provider account CRUD APIs must
not read or call external providers.

### slow_ai.api.templates.save_template

```txt
Arguments: template_name, nodes, edges, layout, template, status, category, description, preview_asset
Application service: slow_ai.application.templates.save_template
Writes: AI Workflow Template
Returns: persisted template payload
```

`save_template` requires a logged-in user and validates the workflow graph
before writing editable template JSON. It does not create an immutable template
version or execute a run. Direct saves may create/update `DRAFT` templates, may
preserve an already `REJECTED` template while editing content, and may edit
mutable content on a previously `PUBLISHED` template without changing the active
public version. Direct saves must reject direct `IN_REVIEW`, `PUBLISHED`, and
`ARCHIVED` status writes; those lifecycle transitions are only allowed through
the dedicated review APIs. Non-System Manager users may edit only templates they
own.

### slow_ai.api.templates.get_template

```txt
Arguments: template
Application service: slow_ai.application.templates.get_template
Returns: template metadata with parsed nodes, edges, layout, and input schema
```

This internal admin/editor API requires a logged-in user. System Managers may
view any template; normal users may view only templates they own. Public Tool
pages must use `slow_ai.api.public_tools.get_template` for runnable published
template payloads.

### slow_ai.api.templates.list_templates

```txt
Arguments: status, category
Application service: slow_ai.application.templates.list_templates
Returns: template summaries
```

This internal admin/editor API requires a logged-in user. System Managers may
list all templates. Normal users receive only templates they own. Public Tool
pages must use `slow_ai.api.public_tools.list_templates`, which exposes only
published templates backed by active immutable versions.

### slow_ai.api.templates.create_workflow_from_template

```txt
Arguments: template, project, title
Application service: slow_ai.application.templates.create_workflow_from_template
Writes: AI Workflow draft
Returns: workflow draft payload
```

This method creates an editable workflow draft only. It must not start a run,
create an immutable version, enqueue workers, or call providers.
It uses the same internal template access policy as `get_template`: System
Managers may instantiate any internal template, while normal users may
instantiate only templates they own. Published user-facing tools must use the
`slow_ai.api.public_tools.*` prepare/create APIs.

### slow_ai.api.templates.submit_template_for_review

```txt
Arguments: template
Application service: slow_ai.application.templates.submit_template_for_review
Writes: AI Workflow Template review status and submit metadata
Returns: persisted template payload
```

Owners may submit their own `DRAFT` or `REJECTED` templates. System Managers
may submit any eligible template. Submission validates graph JSON, template
input schema, public metadata, preview asset references, unsafe secret/provider
targets, and provider-node model metadata. It must not call providers, create
provider jobs, create workflow versions, enqueue workers, or start runs.

### slow_ai.api.templates.approve_template

```txt
Arguments: template, review_notes
Application service: slow_ai.application.templates.approve_template
Writes: AI Workflow Template status, review metadata, published_at
Returns: persisted template payload
```

Only System Managers may approve `IN_REVIEW` templates. Approval performs the
same publication validation as submission and makes the template visible to
public tool APIs by creating a new immutable `AI Workflow Template Version`,
marking the prior active version `SUPERSEDED`, setting status to `PUBLISHED`,
and storing the active version in `published_version`.

### slow_ai.api.templates.list_template_versions

```txt
Arguments: template
Application service: slow_ai.application.templates.list_template_versions
Returns: safe AI Workflow Template Version summaries
```

Owners and System Managers may list versions for templates they can administer.
The payload includes safe metadata such as version number, status, snapshot hash,
approval timestamps, and template metadata. It must not expose raw provider
payloads, provider account names, provider secrets, or workflow execution data.

### slow_ai.api.templates.get_template_version

```txt
Arguments: template_version
Application service: slow_ai.application.templates.get_template_version
Returns: safe AI Workflow Template Version detail
```

The detail payload includes safe immutable version metadata for admin review.
Raw snapshot JSON remains server-side for rollback validation and public-version
materialization. This API must not create ProviderJob, Workflow Version,
Workflow Run, Node Run, Asset, or Ledger records and must not call providers.

### slow_ai.api.templates.rollback_template_to_version

```txt
Arguments: template, template_version, review_notes
Application service: slow_ai.application.templates.rollback_template_to_version
Writes: AI Workflow Template, AI Workflow Template Version
Returns: persisted template payload
```

Only System Managers may rollback. Rollback validates the selected historical
version belongs to the template, validates the snapshot, creates a new ACTIVE
immutable version copied from the historical version, marks the previous active
version `ROLLED_BACK`, updates mutable template JSON to match the rolled-back
snapshot, and keeps the template `PUBLISHED`. It must not start runs, enqueue
workers, create provider jobs, create workflow execution records, create assets,
create ledger rows, or call providers.

### slow_ai.api.templates.reject_template

```txt
Arguments: template, rejection_reason
Application service: slow_ai.application.templates.reject_template
Writes: AI Workflow Template status and review metadata
Returns: persisted template payload
```

Only System Managers may reject `IN_REVIEW` templates. Rejection requires a
non-empty reason and returns the template to an owner-editable `REJECTED` state.

### slow_ai.api.templates.archive_template

```txt
Arguments: template, reason
Application service: slow_ai.application.templates.archive_template
Writes: AI Workflow Template archived status and review metadata
Returns: persisted template payload
```

Only System Managers may archive templates. Archived templates are rejected by
public tool APIs and cannot be used to create public tool runs.

### slow_ai.api.public_tools.list_templates

```txt
Arguments: category
Application service: slow_ai.application.public_tools.list_templates
Returns: published AI Workflow Template summaries
```

This user-facing API requires a logged-in session and returns only published
templates backed by an ACTIVE immutable `AI Workflow Template Version`. Mutable
edits to a published template are not exposed until approved into a new version.
It must not expose provider secrets, provider URLs, raw provider responses, or
unpublished template payloads.

### slow_ai.api.public_tools.get_template

```txt
Arguments: template
Application service: slow_ai.application.public_tools.get_template
Returns: one published template payload with parsed nodes, edges, and layout
```

Unpublished or archived templates are rejected. The returned payload is the
active immutable template version, including `template_version`, `version_no`,
and `snapshot_hash`. Loading a public tool template must not create a workflow,
start a run, enqueue workers, create provider jobs, or call providers.

### slow_ai.api.public_tools.create_workflow_from_template

```txt
Arguments: template, project, title
Application service: slow_ai.application.public_tools.create_workflow_from_template
Writes: AI Workflow draft
Returns: editable workflow draft payload
```

This method requires a logged-in user, a published template, and access to the
selected `AI Project`. It delegates to the normal template/workflow services to
create an editable draft only. Runs still start exclusively through
`slow_ai.api.runs.start_run`, so graph validation, run preflight, and billing
balance checks remain authoritative.

### slow_ai.api.public_tools.prepare_workflow_from_template

```txt
Arguments: template, project, title, values
Application service: slow_ai.application.public_tools.prepare_workflow_from_template
Writes: AI Workflow draft
Returns: editable workflow draft payload
```

This method requires a logged-in user, a published template, and EDITOR/OWNER
access to the selected `AI Project`. When the template has `input_schema_json`,
submitted values are validated by the backend schema policy before being
written into allowed node config fields. Templates without an input schema use
the legacy node-derived public-tool field allow-list.

`prepare_workflow_from_template` must not start a run, create an immutable
workflow version, enqueue workers, create node runs, create provider jobs,
create assets, create ledger rows, or call providers. Runs still start only
through `slow_ai.api.runs.start_run`. Drafts created by this method are marked
as temporary public tool drafts so stale unstarted drafts can be cleaned later.

### slow_ai.api.public_tools.prepare_rerun_from_run

```txt
Arguments: workflow_run, title
Application service: slow_ai.application.public_tools.prepare_rerun_from_run
Writes: AI Workflow draft
Returns: editable rerun draft payload
```

This method creates a new editable draft from the immutable template version
recorded on the source run. It must not create workflow versions, workflow
runs, node runs, provider jobs, assets, ledger rows, enqueue workers, or call
providers. Rerun drafts created by this method are marked as temporary public
tool drafts so stale unstarted reruns can be cleaned later.

### slow_ai.api.public_tools.cleanup_stale_tool_drafts

```txt
Arguments: max_age_hours, limit, dry_run
Application service: slow_ai.application.public_tools.cleanup_stale_tool_drafts
Writes: deletes stale AI Workflow drafts only
Returns: safe cleanup counts, deleted workflow ids, skipped workflow ids/reasons
```

This API is System Manager-only. It deletes only `AI Workflow` rows that are
explicitly marked as temporary public tool drafts, are older than the configured
age threshold, still have template-version lineage, and have no `AI Workflow
Run` or `AI Workflow Version`. It must not delete or mutate `AI Workflow
Version`, `AI Workflow Run`, `AI Node Run`, `AI Provider Job`, `AI Asset`,
`AI Credit Ledger`, or `AI Tool Run Share` records. It must not call providers,
enqueue workers, expose provider accounts, expose provider secrets, expose raw
provider payloads, or expose provider URLs. The public Tool page must not call
this API.

### slow_ai.api.public_tools.list_my_runs

```txt
Arguments: project, limit, include_archived
Application service: slow_ai.application.public_tools.list_my_runs
Returns: scoped AI Workflow Run summaries
```

This user-facing run library API requires a logged-in session. System Managers
may list all runs. Normal users may list only runs for projects they own unless
a future project membership model extends this rule. Summaries include safe run
status, workflow title, project, timestamps, provider status counts, asset
count, and cost totals. They must not expose provider accounts, provider
secrets, raw provider responses, raw provider errors, or provider URLs. Archived
runs are hidden by default and returned only when `include_archived` is truthy
and the caller still has run/project access.

### slow_ai.api.public_tools.get_my_run

```txt
Arguments: workflow_run
Application service: slow_ai.application.public_tools.get_my_run
Returns: scoped safe run detail
```

This API enforces the same project access rule as `list_my_runs`. It returns
safe run/node/provider/asset/ledger summaries for display in the Tool Run
Library. It may include the reusable `output_gallery` payload assembled by
`slow_ai.application.run_outputs`; preview URLs and files inside that gallery
come from the backend asset view service. Provider raw request/response/error
JSON, provider account names, API keys, and provider URLs must not be returned.
Node output details are reduced to a safe summary of asset names and non-sensitive
top-level keys through `slow_ai.application.safe_payloads`; raw node output JSON
is not returned.

All authenticated run detail reads are read-only. Calling `get_my_run`,
`get_run_output_gallery`, `list_my_runs`, `get_run_status`, `get_history`,
`get_run_timeline`, or `assets.view` must not create, delete, enqueue, or mutate
workflow versions, workflow runs, node runs, provider jobs, assets, ledger rows,
or share records. Guest `get_shared_run` has the same read-only side-effect
contract for shared output views.

### slow_ai.api.public_tools.get_run_output_gallery

```txt
Arguments: workflow_run
Application service: slow_ai.application.public_tools.get_run_output_gallery
Returns: scoped run metadata, grouped safe output assets, and selected/shareable flags
```

This API requires a logged-in user and project view access. It builds a
read-only gallery payload from persisted `AI Asset` rows and safe `AI Node Run`
output asset references, then resolves previews through
`slow_ai.application.assets.view`. It must not create workflow versions,
workflow runs, node runs, provider jobs, assets, ledger rows, workers, or
provider calls. It must not expose provider account names, provider secrets,
raw provider request/response/error JSON, workflow draft internals, or unsafe
errors.

### slow_ai.api.public_tools.cancel_my_run

```txt
Arguments: workflow_run
Application service: slow_ai.application.public_tools.cancel_my_run
Writes: existing AI Workflow Run, non-terminal AI Node Run rows, and local non-terminal AI Provider Job rows
Returns: safe cancelled run summary
```

This API requires a logged-in user with project edit access: project owner,
OWNER, EDITOR, or System Manager. VIEWER and BILLING members must be rejected.

Cancellation is allowed only while the workflow run is `QUEUED`, `RUNNING`, or
`WAITING_PROVIDER`. It marks the workflow run `CANCELLED` with a safe
user-facing cancellation message. Non-terminal node runs are marked
`CANCELLED`. Local persisted provider jobs in non-terminal states are marked
`CANCELLED` without calling external provider cancel APIs.

The API must not call providers, enqueue workers, create workflow versions,
workflow runs, node runs, provider jobs, assets, or ledger rows. Public payloads
must not expose provider account names, provider secrets, raw provider
request/response/error JSON, provider URLs, or unsafe errors.

### slow_ai.api.public_tools.archive_my_run

```txt
Arguments: workflow_run
Application service: slow_ai.application.public_tools.archive_my_run
Writes: existing AI Workflow Run archive fields only
Returns: safe archived run summary
```

This API requires a logged-in user with project edit access: project owner,
OWNER, EDITOR, or System Manager. VIEWER and BILLING members must be rejected.

Archiving is allowed only for terminal workflow runs. Active runs are rejected;
archive does not cancel runs, stop provider polling, or change execution state.
Archiving hides the run from default `list_my_runs` results while preserving
audit records and allowing `get_my_run` to open the archived run for users with
view access.

The API must not delete records, call providers, enqueue workers, create
workflow versions, workflow runs, node runs, provider jobs, assets, ledger rows,
or share rows. It must not mutate AI Workflow Version, AI Node Run, AI Provider
Job, AI Asset, AI Credit Ledger, or AI Tool Run Share records. Public payloads
must not expose provider account names, provider secrets, raw provider
request/response/error JSON, provider URLs, or unsafe errors.

### slow_ai.api.public_tools.create_run_share

```txt
Arguments: workflow_run, selected_assets, expires_at
Application service: slow_ai.application.public_tools.create_run_share
Writes: AI Tool Run Share
Returns: safe share metadata and read-only share URL
```

This API requires a logged-in user with access to the run project. Only
completed successful tool runs may be shared. `selected_assets` is required,
must contain at least one AI Asset name, and every selected asset must belong to
the workflow run. Empty selection is rejected; there is no implicit share-all
fallback. It must not create workflow versions, workflow runs, node runs,
provider jobs, assets, ledger rows, workers, or provider calls.

### slow_ai.api.public_tools.disable_run_share

```txt
Arguments: share_token, share
Application service: slow_ai.application.public_tools.disable_run_share
Writes: AI Tool Run Share.status = DISABLED
Returns: safe share metadata
```

Only the share owner or System Manager may disable a share. Disabling a share
must not mutate the underlying workflow run or output records.

### slow_ai.api.public_tools.get_shared_run

```txt
Arguments: share_token
Application service: slow_ai.application.public_tools.get_shared_run
Guest access: allowed
Returns: safe read-only run metadata, selected output asset previews, and aggregate cost summary
```

This API allows guest reads only for ACTIVE, non-expired share tokens. It must
not return provider account names, provider secrets, raw provider
request/response/error JSON, workflow draft internals, or unsafe errors. It
must not start runs, enqueue workers, create provider jobs, create assets,
create ledger rows, or call providers. It returns only assets persisted in
`AI Tool Run Share.selected_assets_json` and must not recompute all run assets
for guest display.

## Layer rule

API modules may import only application services and Frappe whitelisting
helpers. They must not import `engine/`, `providers/`, `node_registry/`, or
DocType controllers.

## Task 10 canvas usage

The `/app/slow-ai-canvas` Desk Page may call only whitelisted API methods for
workflow editing and monitoring:

```txt
slow_ai.api.nodes.get_object_info
slow_ai.api.workflows.get_workflow
slow_ai.api.workflows.save_workflow
slow_ai.api.runs.start_run
slow_ai.api.runs.get_run_status
slow_ai.api.runs.get_history
slow_ai.api.queue.get_queue_status
slow_ai.api.assets.upload
slow_ai.api.assets.view
slow_ai.api.models.get_model_metadata
slow_ai.api.models.list_models
slow_ai.api.models.get_model
slow_ai.api.models.update_model_status
slow_ai.api.models.update_model_pricing
slow_ai.api.models.update_model_metadata
slow_ai.api.provider_accounts.list_accounts
slow_ai.api.provider_accounts.get_account
slow_ai.api.provider_accounts.create_account
slow_ai.api.provider_accounts.set_default
slow_ai.api.provider_accounts.disable_account
slow_ai.api.public_tools.list_templates
slow_ai.api.public_tools.get_template
slow_ai.api.public_tools.prepare_workflow_from_template
slow_ai.api.public_tools.list_my_runs
slow_ai.api.public_tools.get_my_run
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
slow_ai.api.templates.list_templates
slow_ai.api.templates.get_template
slow_ai.api.templates.save_template
slow_ai.api.templates.create_workflow_from_template
slow_ai.api.templates.submit_template_for_review
slow_ai.api.templates.approve_template
slow_ai.api.templates.reject_template
slow_ai.api.templates.archive_template
slow_ai.api.templates.list_template_versions
slow_ai.api.templates.get_template_version
slow_ai.api.templates.rollback_template_to_version
```

The canvas must not call providers, create provider jobs directly, read provider
secrets, or execute workflows inside client JavaScript. Template library actions
may save `AI Workflow Template` records and create editable `AI Workflow` drafts
only; they must not start runs, create immutable workflow versions, enqueue
workers, or call providers.

Tool Mode uses the same whitelist. It may load a template, create an editable
workflow draft from that template, upload/select files for `upload_asset`
fields, create or reference final `AI Asset` records through
`slow_ai.api.assets.upload` and `slow_ai.api.assets.view`, write form values back through
`slow_ai.api.workflows.save_workflow`, and then run only through
`slow_ai.api.runs.start_run`. It must not introduce a second execution API or
call providers from client assets.

The Model Catalog panel uses the same whitelist. It may list and inspect safe
`AI Model` metadata through `slow_ai.api.models.list_models` and
`slow_ai.api.models.get_model`, and may update status/pricing only through the
thin admin model APIs. These actions must not call providers, create provider
jobs, expose provider account data, expose provider secrets, or weaken
server-side run preflight.

## Public tool page usage

The `/app/slow-ai-tools` Desk Page is a user-facing Tool Run page. It may call
only:

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
slow_ai.api.assets.upload
slow_ai.api.assets.view
slow_ai.api.billing.get_balance
slow_ai.api.models.get_model_metadata
slow_ai.api.projects.list_members
slow_ai.api.projects.add_member
slow_ai.api.projects.update_member_role
slow_ai.api.projects.disable_member
```

The page must prepare an editable workflow draft from a published template by
submitting validated form values through
`slow_ai.api.public_tools.prepare_workflow_from_template`, and then start only
through `start_run`. It must not call `save_workflow` directly from the public
Tool Run page, call providers, create provider jobs directly, expose provider
accounts or secrets, execute workflow logic in JavaScript, or bypass run
preflight and billing balance policy. Its Tool Run Library must list and load
run detail only through the scoped public tool run APIs, and output gallery
previews must be loaded through `slow_ai.api.public_tools.get_run_output_gallery`
or the `output_gallery` included in `get_my_run`. Direct `assets.view` calls on
the public page remain allowed for user-selected input asset preview/upload
workflows, not for rebuilding run outputs from raw history.

The public Tool Run page may create and disable read-only share links through
`slow_ai.api.public_tools.create_run_share` and
`slow_ai.api.public_tools.disable_run_share`. The guest shared page may call
only `slow_ai.api.public_tools.get_shared_run`. Neither page may call
`start_run` from a shared link, call providers, create provider jobs, expose
provider account names, expose provider secrets, or expose raw provider
payloads.

## Project membership API

Project membership APIs are thin delegates to `slow_ai.application.project_access`:

```txt
slow_ai.api.projects.list_my_projects
slow_ai.api.projects.list_members
slow_ai.api.projects.add_member
slow_ai.api.projects.update_member_role
slow_ai.api.projects.disable_member
```

Payloads expose safe membership metadata only: project, user, role, status,
owner, creation, and modified timestamps. They must not expose provider
accounts, provider secrets, provider URLs, raw provider payloads, workflow
draft internals, or billing ledger internals.

`AI Project Member` has Frappe change tracking enabled. Membership add/update/
disable operations may create normal Frappe `Version` audit rows for the
membership document, but they must not create workflow versions, workflow runs,
node runs, provider jobs, assets, credit ledger rows, enqueue workers, or call
providers.

Role enforcement:

```txt
AI Project.owner and System Manager: full project administration
OWNER member: manage members, workflows, runs, shares, billing, provider accounts
EDITOR member: edit workflows/assets, start runs, view runs, create shares
VIEWER member: view workflows/assets/runs only
BILLING member: view/manage billing and provider accounts only
```

Membership API calls must not create workflow versions, workflow runs, node
runs, provider jobs, assets, credit ledger rows, enqueue workers, or call
providers.
