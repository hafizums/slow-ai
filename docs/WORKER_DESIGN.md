# Worker Design

## Core rule

HTTP starts work. Workers execute work.

## Required workers

```txt
workers/run_workflow.py
workers/run_node.py
workers/poll_provider_job.py
workers/resume_workflow.py
workers/cancel_workflow.py
workers/cleanup_failed_runs.py
```

## Polling policy

Prefer short repeated polling jobs.

Do not keep one worker sleeping for many minutes.

## Idempotency policy

Before submitting an external job:

```txt
Check if provider job already exists for node_run and attempt
If submitted, poll instead of resubmitting
If unknown, recover from persisted provider job state
```

## Failure policy

Workers must persist structured errors.

Do not rely only on logs.

## Task 04 implementation

`workers/run_workflow.py` delegates to `slow_ai.engine.executor.run_workflow`.
It expects an existing `AI Workflow Run` created by the application layer.

The worker does not create workflow drafts, call providers, or execute inside a
normal HTTP request.

## Task 08 implementation

Worker entrypoints:

```txt
workers/run_workflow.py
  executes one persisted AI Workflow Run through the workflow executor

workers/run_node.py
  executes one persisted AI Node Run using completed upstream output_json values

workers/poll_provider_job.py
  polls one persisted AI Provider Job through the provider registry and enqueues
  workflow resume when the provider reaches a terminal status

workers/poll_provider_job.py::poll_pending_provider_jobs
  scheduled batch entrypoint that scans persisted AI Provider Job rows in
  SUBMITTED or WAITING_PROVIDER state with an external_job_id and delegates each
  row to poll_provider_job

workers/resume_workflow.py
  resumes one persisted AI Workflow Run through the same workflow executor
```

The workflow executor is resume-aware:

```txt
QUEUED -> RUNNING
WAITING_PROVIDER -> RUNNING
RUNNING remains RUNNING
terminal workflow states are no-ops
SUCCEEDED node runs are skipped and their output_json is reused
WAITING_PROVIDER node runs return the workflow to WAITING_PROVIDER
```

Realtime helpers live in:

```txt
slow_ai/infrastructure/realtime.py
```

Events:

```txt
slow_ai_workflow_run_update
slow_ai_node_run_update
slow_ai_provider_job_update
```

Realtime events are emitted by persistence adapters after DB state updates, with
`after_commit=True`. The database remains the source of truth; realtime is only
a UI notification channel.

## Task 09 provider output polling

When `workers/poll_provider_job.py` receives a terminal provider result for a
node run in `WAITING_PROVIDER`, it updates the node through persisted records:

```txt
SUCCEEDED
  materialize provider outputs through ProviderOutputService
  create or reuse AI Asset records
  create or reuse AI Credit Ledger DEBIT
  mark AI Node Run as SUCCEEDED with output_json

FAILED / EXPIRED
  mark AI Node Run as FAILED with structured error

CANCELLED
  mark AI Node Run as CANCELLED
```

The poll worker does not execute downstream nodes inline. It enqueues workflow
resume after terminal provider status, and the workflow worker continues the
DAG from persisted node outputs.

## Scheduled provider polling

`slow_ai.hooks.scheduler_events` registers:

```txt
slow_ai.workers.poll_provider_job.poll_pending_provider_jobs
```

The scheduled entrypoint runs on Frappe's `all` scheduler event. It does not
submit provider jobs, create provider jobs, or execute downstream graph nodes
inline. It only polls provider jobs that have already been submitted and have a
persisted `external_job_id`. Provider output materialization and workflow resume
remain inside the existing single-job poll worker path.
