# Project Membership Contract

`AI Project Member` extends project access beyond `AI Project.owner` while
keeping provider execution, billing, and run preflight server-side.

## Roles

```txt
AI Project.owner: admin-equivalent project owner
OWNER: manage project members, workflows, assets, runs, shares, billing, provider accounts
EDITOR: edit workflows/assets, start runs, view runs, create shares
VIEWER: view workflows/assets/runs/shares only
BILLING: view/manage billing and provider account settings only
System Manager: cross-project administration
```

Only ACTIVE memberships grant access. DISABLED memberships are ignored.

`AI Project Member` uses Frappe change tracking. Role and status changes should
leave normal Frappe `Version` audit history for the membership row; no custom
audit DocType is required in the current design.

## Central Policy

Project access decisions live in:

```txt
slow_ai.application.project_access
```

Required policy helpers:

```txt
can_view_project
can_edit_project
can_run_project
can_manage_project_members
can_view_billing
can_manage_billing
can_manage_provider_accounts
can_share_run
```

API methods and application services must call these helpers instead of
duplicating role checks.

## API

```txt
slow_ai.api.projects.list_my_projects
slow_ai.api.projects.list_members
slow_ai.api.projects.add_member
slow_ai.api.projects.update_member_role
slow_ai.api.projects.disable_member
```

These APIs return safe metadata only. They must not expose provider account
names through public/share payloads, provider secrets, provider URLs, raw
provider request/response/error JSON, workflow draft internals, or billing
ledger internals.

Membership API responses may include only safe membership metadata:

```txt
project
user
role
status
owner
created
modified
```

## Service Enforcement

```txt
workflows save/create: OWNER or EDITOR
workflows get/list: OWNER, EDITOR, VIEWER, or BILLING
assets upload: OWNER or EDITOR
assets view: OWNER, EDITOR, VIEWER, or BILLING
start_run: OWNER or EDITOR, plus run preflight and billing balance checks
run status/history: OWNER, EDITOR, VIEWER, or BILLING
public tool workflow creation: OWNER or EDITOR
public tool run listing/detail: accessible project members only
share creation: OWNER or EDITOR
share disable: share owner, project OWNER, project owner, or System Manager
billing top-up/ledger: OWNER, BILLING, or System Manager
provider account CRUD: OWNER, BILLING, or System Manager
```

Failed access checks must happen before enqueueing workers or creating
`AI Workflow Version`, `AI Workflow Run`, `AI Node Run`, `AI Provider Job`,
`AI Asset`, or `AI Credit Ledger` records.

## Boundaries

Membership CRUD must not call providers, create provider jobs, enqueue workers,
execute workflows, expose provider secrets, expose raw provider payloads, or
create anonymous paid-run paths. DocType controllers remain persistence-only.

The Public Tool Project Members UI must treat the backend policy as
authoritative. It may show membership write controls only after
`slow_ai.api.projects.list_members` succeeds for the selected project. If the
current user cannot manage members, the UI must show generic safe unavailable
text and must not display raw server/provider payloads.
