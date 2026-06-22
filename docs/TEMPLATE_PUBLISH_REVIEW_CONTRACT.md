# Template Publish Review Contract

## Purpose

Published `AI Workflow Template` records are the catalog source for
`/app/slow-ai-tools`. Templates must pass a controlled review lifecycle before
normal users can run them from the public tool page. Public Tool Mode consumes
the active immutable `AI Workflow Template Version`, not mutable template JSON.

## Lifecycle

```txt
DRAFT -> IN_REVIEW -> PUBLISHED
DRAFT -> IN_REVIEW -> REJECTED -> IN_REVIEW -> PUBLISHED
PUBLISHED -> IN_REVIEW -> PUBLISHED
PUBLISHED -> ROLLBACK_VERSION -> PUBLISHED
PUBLISHED -> ARCHIVED
REJECTED -> ARCHIVED
IN_REVIEW -> ARCHIVED
```

`DRAFT` and `REJECTED` are owner-editable states. `IN_REVIEW`, `PUBLISHED`,
`REJECTED`, and `ARCHIVED` review transitions are controlled by application
services, not by DocType controller logic.

Approval creates a new ACTIVE `AI Workflow Template Version` snapshot and marks
the previous active snapshot `SUPERSEDED`. Rollback is a System Manager action
that validates a historical snapshot, creates a new ACTIVE version copied from
that snapshot, marks the previous active version `ROLLED_BACK`, and keeps the
template `PUBLISHED`.

## APIs

```txt
slow_ai.api.templates.submit_template_for_review
slow_ai.api.templates.approve_template
slow_ai.api.templates.reject_template
slow_ai.api.templates.archive_template
slow_ai.api.templates.list_template_versions
slow_ai.api.templates.get_template_version
slow_ai.api.templates.rollback_template_to_version
```

These APIs are thin Frappe whitelisted delegates into
`slow_ai.application.templates`.

`slow_ai.api.templates.save_template` is not a lifecycle transition API. It
requires a logged-in user and may create/update editable template content only.
New template saves must be `DRAFT`. Existing `REJECTED` templates may be edited
only while preserving `REJECTED`. Existing `PUBLISHED` templates may have
mutable draft content edited while preserving `PUBLISHED`, but public payloads
must continue using the active immutable version until the template is approved
again. Direct saves must reject direct `IN_REVIEW`, `PUBLISHED`, and `ARCHIVED`
status writes even for System Managers.

## Permissions

Internal template library APIs are owner/System Manager surfaces. System
Managers may list, view, instantiate, submit, approve, reject, archive, and
rollback templates according to the lifecycle. Normal users may list/view/save
and instantiate only templates they own, and may submit only their own `DRAFT`
or `REJECTED` templates for review. Only System Managers may approve, reject,
archive, or rollback templates.

Normal public tool users may list, load, prepare, and run only `PUBLISHED`
templates through `slow_ai.api.public_tools.*`.

## Publication Validation

Submission and approval validate:

```txt
workflow graph JSON
template input schema targets and types
category and description
preview_asset reference if present
secret/provider/internal payload fragments
unsafe input schema targets such as provider_account or api keys
provider-node provider/model metadata when provider nodes are present
disabled provider models
provider/model mismatch
node_type/model mismatch
```

Validation must not call providers, inspect provider secrets, create provider
jobs, create workflow versions, enqueue workers, or execute workflows.
Approval and rollback additionally validate and persist immutable template
version snapshots. This versioning step is not workflow execution and must not
create `AI Workflow Version` records.

## Public Tool Gate

`slow_ai.application.public_tools` must treat `PUBLISHED` as the only runnable
template status. `DRAFT`, `IN_REVIEW`, `REJECTED`, and `ARCHIVED` templates are
hidden from the public tool template list and rejected by public tool load and
prepare APIs.

For `PUBLISHED` templates, public list, detail, and prepare APIs must load the
ACTIVE `AI Workflow Template Version` snapshot. Mutable edits to the parent
template must not appear in public payloads until a new approval creates a new
active version.

## Side Effects

Template review actions may update only `AI Workflow Template` fields and
`AI Workflow Template Version` status/snapshot rows:

```txt
status
submitted_by
submitted_at
reviewed_by
reviewed_at
review_notes
rejection_reason
published_at
published_version
modified
```

They must not create:

```txt
AI Workflow
AI Workflow Version
AI Workflow Run
AI Node Run
AI Provider Job
AI Asset
AI Credit Ledger
```

They must not enqueue workers or call providers.

Review lifecycle actions are audited through the tracked `AI Workflow Template`
row and, for approval, immutable `AI Workflow Template Version` business
records. Rejected lifecycle attempts must not create misleading template
versions or execution/billing/share records.

## Frontend Boundary

The canvas Template Library may call the review APIs for admin review actions.
The Save Template prompt may offer only direct-save statuses allowed by
`save_template`; it must not offer direct `PUBLISHED` or `ARCHIVED` options.
The Template Library may list approved versions and rollback through the
dedicated rollback API, but it must not mutate version snapshots in the browser.
The Template Library remains an editor/admin surface only. It must not call
provider URLs, expose provider secrets, import provider adapters, create
provider jobs, or execute workflow logic in client JavaScript.
