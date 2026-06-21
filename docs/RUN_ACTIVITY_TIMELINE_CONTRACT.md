# Run Activity Timeline Contract

## Purpose

`slow_ai.api.runs.get_run_timeline` returns a safe, backend-generated activity
timeline for a workflow run. It is for logged-in users and admins who already
have project view access and need to understand what happened during execution
without reading raw provider payloads.

The timeline is a derived read model. It must not add a DocType or persist
timeline rows unless a future retention requirement explicitly needs that.

## Source Records

Timeline events are generated from persisted records only:

```txt
AI Workflow Run
AI Node Run
AI Provider Job
AI Asset
AI Credit Ledger
AI Tool Run Share
```

The service must not call providers, enqueue workers, or read client-side state.

## Safe Event Payload

Each event may include:

```txt
timestamp
event_type
title
message
related_doctype
related_name
node_id
node_type
status
amount_usd
currency
```

Supported event types include:

```txt
RUN_QUEUED
RUN_STARTED
NODE_STARTED
PROVIDER_JOB_CREATED
PROVIDER_JOB_SUBMITTED
PROVIDER_JOB_POLLED
PROVIDER_JOB_SUCCEEDED
PROVIDER_JOB_FAILED
PROVIDER_JOB_EXPIRED
ASSET_CREATED
CREDIT_RESERVED
CREDIT_RELEASED
CREDIT_DEBITED
RUN_CANCELLED
RUN_ARCHIVED
RUN_SUCCEEDED
RUN_FAILED
RUN_EXPIRED
```

The service may add other safe metadata-only event types, such as share-link
creation or disabled-share events, as long as they do not expose tokens.

## Forbidden Payload

The timeline must not expose:

```txt
provider account names
provider secrets
API keys
raw request_json
raw response_json
raw_error_json
raw provider URLs
workflow draft internals
provider adapter internals
```

Failure, timeout, and cancellation events must use safe generic messages. Raw
provider error bodies remain server-side only. Safe text redaction and
sensitive-key detection should use `slow_ai.application.safe_payloads` so
timeline, run status/history, public tool detail, and asset view behavior do
not drift.

## Read-Only Boundary

Calling the timeline API must create no:

```txt
AI Workflow Version
AI Workflow Run
AI Node Run
AI Provider Job
AI Asset
AI Credit Ledger
AI Tool Run Share
queue job
provider request
```

Existing archive, cancel, reservation, quota, idempotency, timeout, cleanup,
and output-gallery behavior must remain unchanged.

The same read-only side-effect guard applies to adjacent run detail reads used
by authenticated Canvas/Public Tool pages and guest shared pages:
`get_run_status`, `get_history`, `get_my_run`, `get_run_output_gallery`,
`list_my_runs`, `get_shared_run`, and `assets.view` must not create, delete,
enqueue, or mutate execution, billing, asset, or share records merely by being
called.

## Public Tool Usage

The Public Tool page may render a run timeline only through this safe backend
API. The shared guest page must not expose the internal run timeline in this
milestone.

Authenticated Canvas and Public Tool run detail views may render timeline
events from `slow_ai.api.runs.get_run_timeline`. They may display only safe
event fields: timestamp, title, message, status, node id/type, and safe
amount/currency. Guest shared-output pages must not call the timeline API or
render internal timeline events.

Authenticated timeline clients must render explicit loading, empty, success,
and failure states. Timeline fetch failures must show only a generic safe UI
message such as `Timeline unavailable`; clients must not display raw server
exceptions, provider errors, response JSON, provider URLs, API keys,
Authorization headers, provider account names, or workflow draft internals.
Timeline rows must be backed only by this API and not reconstructed from
history payloads. Authenticated clients should ignore stale timeline responses
when the selected/open run changes before the request completes.

Authenticated clients may add local search and filters for safe fields such as
event type, status, and node id. Filtering must happen client-side over the
already returned safe timeline payload and must not call providers, enqueue
workers, mutate records, request raw history to rebuild events, or expose
forbidden payload fields. Guest shared-output pages must not show the internal
timeline or timeline filters.
