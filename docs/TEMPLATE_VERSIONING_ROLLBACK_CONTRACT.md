# Template Versioning Rollback Contract

## Purpose

`AI Workflow Template` is editable authoring state. Public Tool Mode must run
only an approved immutable `AI Workflow Template Version` snapshot.

## Version Creation

Approval through `slow_ai.api.templates.approve_template` creates a new
`AI Workflow Template Version` row with:

```txt
template
version_no
status = ACTIVE
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

The previous ACTIVE version for the template is marked `SUPERSEDED`. Public
template APIs return the ACTIVE version payload and include `template_version`,
`version_no`, and `snapshot_hash`.

## Immutability

After insert, a template version snapshot is immutable. Application services may
only change `status` to `SUPERSEDED`, `ROLLED_BACK`, or `ARCHIVED`.

DocType controllers are persistence-only. They must not validate publication,
execute workflows, enqueue workers, create provider jobs, call providers, create
assets, or create ledger rows.

## Rollback

Rollback uses `slow_ai.api.templates.rollback_template_to_version`.

Rules:

```txt
System Manager only
target version must belong to the template
target snapshot must validate before rollback
rollback creates a new ACTIVE version copied from the historical snapshot
previous ACTIVE version is marked ROLLED_BACK
template remains PUBLISHED
template.published_version points at the new ACTIVE version
```

Rollback must not create `AI Workflow`, `AI Workflow Version`, `AI Workflow Run`,
`AI Node Run`, `AI Provider Job`, `AI Asset`, or `AI Credit Ledger` records. It
must not enqueue workers or call providers.

## Public Tool Behavior

Public Tool Mode APIs must not read mutable template JSON for runnable payloads.
They must read the active immutable version snapshot. Editing a published
template through `save_template` must not alter public payloads until the edited
template is submitted and approved again.

Public Tool reruns must read the immutable template version recorded on the
source `AI Workflow Run` lineage. Rerun preparation must not switch to the
current ACTIVE version, and it must continue to use the recorded historical
version after later template edits, reapproval, rollback, or archive, provided
the recorded version snapshot hash and safe payload validation still pass.

Rerun preparation may create a new editable `AI Workflow` draft with the same
`source_template` and `source_template_version` lineage. It must not create
`AI Workflow Version`, `AI Workflow Run`, `AI Node Run`, `AI Provider Job`,
`AI Asset`, or `AI Credit Ledger` rows, enqueue workers, or call providers.

## Frontend Boundary

Canvas UI may list version summaries and request rollback through backend APIs.
It must not execute rollback logic, mutate snapshots, call providers, expose
provider secrets/account names/raw provider payloads, or start runs from template
version actions.
