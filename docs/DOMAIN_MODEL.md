# Domain Model

## Core entities

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
```

## Relationships

```txt
AI Project
  └── AI Workflow
        ├── AI Workflow Version
        └── AI Workflow Run
              ├── AI Node Run
              │     ├── AI Provider Job
              │     └── AI Asset
              └── AI Credit Ledger
```

## AI Workflow

Editable draft. Never execute this directly.

## AI Workflow Version

Immutable execution snapshot. Every run references one version.

## AI Workflow Run

One execution of one workflow version.

## AI Node Run

One execution of one node inside a workflow run.

## AI Provider Job

One external API job.

Created before an outbound provider request and updated as the provider moves
through `QUEUED`, `SUBMITTING`, `SUBMITTED`, `WAITING_PROVIDER`, and terminal
states. It stores provider request JSON, normalized response JSON, raw error
JSON, external job ID, cost, and lifecycle timestamps.

## AI Asset

A persisted uploaded or generated media record.

## AI Model

Provider model catalog.

## AI Credit Ledger

Append-only cost/credit record.

## AI Workflow Template

Reusable workflow definition.

Templates store validated workflow draft JSON for reuse. Creating a workflow
from a template creates an editable `AI Workflow` draft and does not create
`AI Workflow Version`, `AI Workflow Run`, `AI Node Run`, provider jobs, assets,
or ledger rows.
