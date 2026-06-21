# DocType Design

## Core principle

DocTypes are persistence only.

Do not place workflow execution or provider calls in DocType controllers.

## Required DocTypes

```txt
AI Project
AI Workflow
AI Workflow Version
AI Workflow Run
AI Node Run
AI Asset
AI Provider Job
AI Model
AI Provider Account
AI Credit Ledger
AI Workflow Template
AI Tool Run Share
```

## AI Workflow

Suggested fields:

```txt
project
title
status
draft_nodes_json
draft_edges_json
layout_json
current_version
```

## AI Workflow Version

Suggested fields:

```txt
workflow
version_no
nodes_json
edges_json
layout_json
snapshot_hash
created_by
created_at
```

Rules:

```txt
Immutable after creation
Must be created before AI Workflow Run
Must not be replaced by draft workflow
```

## AI Workflow Run

Suggested archive fields:

```txt
is_archived
archived_by
archived_at
```

Archive fields are user-library visibility metadata only. They must not drive
workflow execution, provider polling, billing, asset materialization, or share
visibility. Active-run rejection, project access checks, and hide/show listing
rules live in application services; the DocType controller remains
persistence-only.

## AI Node Run

Suggested fields:

```txt
workflow_run
node_id
node_type
status
input_json
config_json
output_json
error_json
provider_job
cost_usd
started_at
completed_at
attempt_no
input_hash
config_hash
cache_key
cache_hit
```

## AI Provider Job

Suggested fields:

```txt
provider
provider_account
model
external_job_id
status
idempotency_key
estimated_cost_usd
cost_usd
debit_cost_usd
debit_cost_source
last_polled_at
poll_attempts
max_poll_attempts
timeout_seconds
retry_count
max_retries
submitted_at
completed_at
request_json
response_json
raw_error_json
```

## AI Asset

Suggested fields:

```txt
project
asset_type
file
url
mime_type
width
height
duration_seconds
source_workflow_run
source_node_run
source_provider_job
metadata_json
```

## AI Model

Suggested fields:

```txt
model_id
model_slug
model_name
provider
status
node_type
category
modality
pricing_json
capabilities_json
input_metadata_json
output_metadata_json
```

The controller performs persistence-only validation: required identity fields,
status values, unique slug, and JSON-object shape for metadata fields. Pricing
semantics are parsed in application services, not in the DocType controller.

## AI Provider Account

Suggested fields:

```txt
provider
account_label
project
user
api_key_secret
is_default
status
rate_limit_json
```

`project` and `user` are optional scope fields used by run preflight and
provider job creation. Empty scope means the account is not restricted by that
dimension. Secrets must not be stored in normal plain text fields or returned
from API methods.

`rate_limit_json` may store safe server-side provider account concurrency
configuration such as:

```json
{"max_active_provider_jobs": 2}
```

The controller only validates JSON shape. Enforcement lives in application
preflight services.

## AI Project Quotas

`AI Project` stores optional run quota and spend-cap fields:

```txt
max_active_runs
max_active_runs_per_user
daily_project_spend_cap_usd
daily_user_spend_cap_usd
```

Blank or zero values mean unset. These fields are configured by admins in Desk
and enforced by `slow_ai.application.run_quota_policy` during run preflight.
The DocType controller remains persistence-only and does not count runs, jobs,
or ledger rows.

## AI Credit Ledger

Append-only.

`CREDIT` rows increase project balance, `RESERVE` rows hold estimated provider
cost before enqueue, `RELEASE` rows offset reservation holds, `DEBIT` rows
record final provider cost, and `ADJUSTMENT` rows apply signed balance
corrections. `metadata_json` may store safe provider/model estimate context for
reservation rows. Balance calculation, reservation, release, settlement, and
top-up orchestration live in application services, not in the DocType
controller.

## Task 02 implementation

Core Frappe DocType metadata lives under the `Slow Ai` module package:

```txt
slow_ai/slow_ai/doctype/ai_project/
slow_ai/slow_ai/doctype/ai_project_member/
slow_ai/slow_ai/doctype/ai_workflow/
slow_ai/slow_ai/doctype/ai_workflow_version/
slow_ai/slow_ai/doctype/ai_workflow_run/
slow_ai/slow_ai/doctype/ai_node_run/
slow_ai/slow_ai/doctype/ai_asset/
slow_ai/slow_ai/doctype/ai_provider_job/
slow_ai/slow_ai/doctype/ai_model/
slow_ai/slow_ai/doctype/ai_provider_account/
slow_ai/slow_ai/doctype/ai_credit_ledger/
slow_ai/slow_ai/doctype/ai_workflow_template/
slow_ai/slow_ai/doctype/ai_workflow_template_version/
slow_ai/slow_ai/doctype/ai_tool_run_share/
```

Controllers are persistence-only. They must not call providers, run workflow
execution, enqueue workers, or import engine/node/provider layers.

Light persistence invariants:

```txt
AI Workflow Version is immutable after creation.
AI Workflow Template Version is immutable after creation except status changes
that mark old published snapshots as SUPERSEDED, ROLLED_BACK, or ARCHIVED.
AI Credit Ledger is append-only after creation.
AI Provider Account stores API credentials in api_key_secret as a Password field.
AI Provider Account controllers perform only light persistence validation and
must not resolve, test, or call providers.
```

The real integration coverage for these DocTypes lives in:

```txt
slow_ai/tests/integration/test_core_doctypes.py
```

## Task 11 workflow template foundation

`AI Workflow Template` fields:

```txt
template_name
status: DRAFT / IN_REVIEW / PUBLISHED / REJECTED / ARCHIVED
category
description
preview_asset
nodes_json
edges_json
layout_json
input_schema_json
submitted_by
submitted_at
reviewed_by
reviewed_at
review_notes
rejection_reason
published_at
published_version
```

`published_version` points to the active immutable `AI Workflow Template Version`
snapshot currently served by public Tool Mode APIs.

`AI Workflow Template Version` fields:

```txt
template
version_no
status: ACTIVE / SUPERSEDED / ROLLED_BACK / ARCHIVED
snapshot_hash
template_name
category
description
preview_asset
nodes_json
edges_json
layout_json
input_schema_json
approved_by
approved_at
source_template_modified
owner
```

Approval and rollback create new version rows. Existing version rows cannot
mutate their snapshot content, metadata, hash, owner, or approval fields.
Controllers remain persistence-only and must not validate publication, execute
workflows, create runs, create provider jobs, create assets, create ledger rows,
enqueue workers, or call providers.

Template DocType controllers remain persistence-only. Graph validation and
template-to-workflow creation live in the application layer.
`input_schema_json` stores backend-validated public/tool form field metadata
and allowed target node config fields. The DocType does not validate schema
business rules; schema parsing, unsafe-target rejection, and submitted value
validation live in application services.

Template publish review rules also live in application services. Owners may
submit eligible draft/rejected templates for review. System Managers approve,
reject, or archive templates. Review actions update only template metadata and
must not call providers, enqueue workers, create provider jobs, or create
workflow execution records.

## Tool run sharing

`AI Tool Run Share` fields:

```txt
workflow_run
project
share_token
status
selected_assets_json
expires_at
owner
creation
modified
```

Share DocType controllers remain persistence-only. Share token generation,
ownership checks, guest expiry/status checks, and safe shared-run payload
construction live in application services. `selected_assets_json` stores the
explicit AI Asset names selected at share creation. Empty selection is rejected
by the application service; the DocType controller does not enforce business
rules or inspect workflow output records.

## Project Membership

`AI Project Member` fields:

```txt
project
user
role: OWNER / EDITOR / VIEWER / BILLING
status: ACTIVE / DISABLED
owner
creation
modified
```

The DocType controller remains persistence-only. It does not decide access,
call providers, enqueue workers, inspect workflows, inspect billing rows, or
mutate provider accounts. Membership role policy and membership CRUD live in
`slow_ai.application.project_access`.

`AI Project.owner` remains admin-equivalent for backwards compatibility and is
treated like project OWNER access. `System Manager` retains cross-project
administrative access.

## Workspace Registration

Every permanent Slow AI DocType must be added to the private Slow AI workspace
navigation in `slow_ai/infrastructure/workspace.py`. Add a workspace chart only
when the DocType has a meaningful aggregate or operational KPI; otherwise keep
charts empty and navigation-only.
