# Realtime Events

## Purpose

Realtime events update the canvas UI during workflow execution.

The database remains the source of truth.

## Event names

```txt
slow_ai_workflow_run_update
slow_ai_node_run_update
slow_ai_provider_job_update
```

## Payloads

```txt
slow_ai_workflow_run_update
  workflow_run
  status
  error, optional

slow_ai_node_run_update
  workflow_run
  node_run
  status
  outputs, optional
  error, optional
  provider_job, optional

slow_ai_provider_job_update
  provider_job
  status
  external_job_id, optional
  error, optional
```

Events are published after persistence adapters update the database, using
Frappe realtime with `after_commit=True`.

## Security rules

Do not include:

```txt
API keys
Provider secrets
Raw provider headers
Unsafe raw errors
Internal server paths
```

## UI rule

If the browser misses realtime events, it must reload run state from API.
