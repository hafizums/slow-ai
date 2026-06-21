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

Provider job polling is bounded by persisted policy fields on
`AI Provider Job`:

```txt
last_polled_at
poll_attempts
max_poll_attempts
timeout_seconds
retry_count
max_retries
```

`poll_provider_job` checks cancellation and terminal workflow state before
timeout/retry policy. Cancellation wins and must not submit, poll, expire, or
resume provider work. For non-terminal provider jobs, polling stops and marks
the provider job `EXPIRED` when `poll_attempts >= max_poll_attempts` or
`submitted_at + timeout_seconds` has passed. Timeout handling marks the waiting
node run `FAILED` with a safe structured error and marks the workflow run
`EXPIRED` when it is waiting on the provider, or `FAILED` when it is queued or
running.

Automatic provider retry is not enabled by default. Retry metadata is persisted
with `max_retries=0` unless a future explicit retry action changes it. Retrying
must remain bounded and must preserve provider-job idempotency.

## Idempotency policy

Run creation and worker execution must tolerate retries:

```txt
start_run reuses a recent active run for the same unchanged workflow draft
node run creation reuses existing node rows for the same workflow run/node id
terminal workflow runs are worker no-ops
terminal node runs are node-worker no-ops
provider job creation reuses the node-run idempotency key
terminal provider job polling returns persisted state and does not call providers
asset materialization reuses existing provider output assets by output index
ledger debit creation reuses the existing provider-job DEBIT row
```

This policy prevents duplicate `AI Workflow Version`, `AI Workflow Run`,
`AI Node Run`, `AI Provider Job`, `AI Asset`, and `AI Credit Ledger` records
when queue jobs, resume jobs, provider polls, or direct worker invocations are
retried. A terminal `AI Workflow Run` remains terminal even when worker or
resume entrypoints are called again.

## Failure policy

Workers must persist structured errors.

Do not rely only on logs.

## Task 04 implementation

`workers/run_workflow.py` delegates to `slow_ai.engine.executor.run_workflow`.
It expects an existing `AI Workflow Run` created by the application layer.

The worker does not create workflow drafts, call providers, or execute inside a
normal HTTP request.

## Queue and API boundary matrix

Read APIs are observation surfaces only:

```txt
slow_ai.api.queue.get_queue_status
slow_ai.api.runs.get_run_status
slow_ai.api.runs.get_history
slow_ai.api.runs.get_run_timeline
slow_ai.api.public_tools.get_my_run
slow_ai.api.public_tools.get_run_output_gallery
slow_ai.api.public_tools.get_shared_run
slow_ai.api.assets.view
```

Calling these APIs must not enqueue workers, execute workflow nodes, submit
providers, poll providers, create provider jobs, mutate run or provider-job
status, or create asset/ledger/share side effects. Worker execution remains
inside the worker entrypoints below. Client assets must not import worker
modules, provider adapters, `frappe.enqueue`, or direct `frappe.db` access.

## System Manager recovery boundary

Operational recovery is exposed only through System Manager-only application
services and thin `slow_ai.api.runs.*` delegates:

```txt
slow_ai.api.runs.inspect_run_recovery
slow_ai.api.runs.expire_stuck_run
slow_ai.api.runs.resume_run
```

`inspect_run_recovery` is read-only. `resume_run` only enqueues the existing
workflow worker for a non-terminal run. `expire_stuck_run` may mark stale
non-terminal run/node/provider-job state terminal locally and release stale
reservations. These APIs must not call external providers, execute workflow
logic inline, create provider jobs, create assets, create debit rows, or expose
raw provider payloads/secrets. Canvas, Public Tool, and guest shared pages must
not call recovery APIs.

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
  timeout policy also marks AI Workflow Run EXPIRED or FAILED without enqueueing resume

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
persisted `external_job_id`. Jobs without an external id, terminal provider
jobs, cancelled parent runs, and jobs already expired by timeout or max-attempt
policy are skipped or finalized safely without provider calls. Provider output
materialization and workflow resume remain inside the existing single-job poll
worker path.
