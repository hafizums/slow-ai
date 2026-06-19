# Run State Machine

## Workflow run statuses

```txt
DRAFT
QUEUED
RUNNING
WAITING_PROVIDER
SUCCEEDED
FAILED
CANCELLED
EXPIRED
```

## Node run statuses

```txt
PENDING
READY
RUNNING
WAITING_PROVIDER
SUCCEEDED
FAILED
SKIPPED
CANCELLED
```

## Provider job statuses

```txt
QUEUED
SUBMITTING
SUBMITTED
WAITING_PROVIDER
SUCCEEDED
FAILED
CANCELLED
EXPIRED
```

## Terminal states

Workflow terminal:

```txt
SUCCEEDED
FAILED
CANCELLED
EXPIRED
```

Node terminal:

```txt
SUCCEEDED
FAILED
SKIPPED
CANCELLED
```

Provider job terminal:

```txt
SUCCEEDED
FAILED
CANCELLED
EXPIRED
```

Do not introduce new statuses without updating this document and tests.

## Kernel implementation

The status enums and allowed transition maps live in:

```txt
slow_ai/domain/status.py
slow_ai/engine/state_machine.py
```

State transitions are validated before persistence adapters update DocTypes.

## Task 04 engine core

Workflow run execution uses persisted state transitions:

```txt
AI Workflow Run: QUEUED -> RUNNING -> SUCCEEDED
AI Workflow Run: QUEUED -> RUNNING -> FAILED
AI Node Run: PENDING -> READY -> RUNNING -> SUCCEEDED
AI Node Run: PENDING -> READY -> RUNNING -> FAILED
```

Implementation paths:

```txt
slow_ai/application/run_service.py
slow_ai/infrastructure/repositories.py
slow_ai/engine/executor.py
slow_ai/engine/node_runner.py
```

The application service creates immutable `AI Workflow Version`, `AI Workflow
Run`, and `AI Node Run` records. The engine executes only persisted workflow
versions, never editable drafts.

## Task 08 resume behavior

Workflow run execution can resume from persisted state:

```txt
AI Workflow Run: WAITING_PROVIDER -> RUNNING
AI Workflow Run: RUNNING -> WAITING_PROVIDER
```

The executor skips `SUCCEEDED` node runs and reuses their persisted
`output_json`. It does not re-execute terminal node runs. A `WAITING_PROVIDER`
node run returns the workflow to `WAITING_PROVIDER` until provider polling and a
resume worker continue the run.

## Provider timeout behavior

Provider jobs can reach `EXPIRED` through worker-side timeout policy when
`poll_attempts >= max_poll_attempts` or `submitted_at + timeout_seconds` has
passed. Timeout expiry marks the waiting `AI Node Run` as `FAILED` with a safe
structured error and marks the parent `AI Workflow Run` as `EXPIRED` when the
run is waiting on the provider. If the workflow run is already terminal,
including `CANCELLED`, provider timeout logic must not progress it.
