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
provider error bodies remain server-side only.

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

## Public Tool Usage

The Public Tool page may render a run timeline only through this safe backend
API. The shared guest page must not expose the internal run timeline in this
milestone.
