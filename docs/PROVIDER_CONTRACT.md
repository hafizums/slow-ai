# Provider Contract

## Goal

Provider integration must be replaceable and isolated.

The engine must not know WaveSpeed-specific details.

## Provider registry

Provider adapters are selected through `slow_ai.providers.registry.ProviderRegistry`.
The registry maps provider names to `ProviderAdapter` instances and supports
registering multiple adapters without changing engine core.

```txt
ProviderRegistry.register(adapter)
ProviderRegistry.register_many(adapters)
ProviderRegistry.get(provider_name)
ProviderRegistry.provider_names()
```

The default registry contains WaveSpeed and Replicate. Tests may inject
deterministic provider adapters through provider nodes to prove extension
behavior; those adapters are not production providers.

## ProviderAdapter interface

```python
class ProviderJobRequest:
    provider: str
    model: str
    input_data: dict
    node_run_name: str | None
    provider_account_name: str | None
    project_name: str | None
    idempotency_key: str | None
    estimated_cost_usd: Decimal | float | str | None


class ProviderSubmission:
    provider_job_name: str
    model: str
    input_data: dict


class ProviderAdapter:
    provider_name: str

    def create_and_submit_job(self, request: ProviderJobRequest) -> NormalizedProviderResult:
        ...

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        ...

    def poll_job(self, provider_job_name: str) -> dict:
        ...

    def cancel_job(self, provider_job_name: str) -> None:
        ...

    def normalize_result(self, raw_response: dict) -> dict:
        ...

    def estimate_cost(self, model: str, input_data: dict) -> dict:
        ...
```

## Required invariant

Create `AI Provider Job` before submitting an external job. Provider adapters
may expose a convenience method that accepts `ProviderJobRequest`, but that
method must persist `AI Provider Job` first and then submit through
`ProviderSubmission`. Creating a submission without a provider job is invalid.

`AI Provider Job` state changes must follow the domain state machine:

```txt
QUEUED -> SUBMITTING -> SUBMITTED -> WAITING_PROVIDER -> SUCCEEDED
QUEUED -> CANCELLED
SUBMITTING -> FAILED | CANCELLED
SUBMITTED -> SUCCEEDED | FAILED | CANCELLED
WAITING_PROVIDER -> FAILED | CANCELLED | EXPIRED
```

Provider repositories must persist:

```txt
AI Model document name on AI Provider Job.model
active default or configured AI Provider Account on AI Provider Job.provider_account
provider account selected by provider/project/user scope
request_json before submit
estimated_cost_usd before submit
external_job_id when the provider returns it
response_json for provider responses
raw_error_json for normalized provider errors
cost_usd for actual normalized provider cost when available
debit_cost_usd and debit_cost_source after materialization
last_polled_at, poll_attempts, and max_poll_attempts for bounded polling
timeout_seconds for worker-side provider job expiration
retry_count and max_retries for explicit bounded retry policy metadata
submitted_at and completed_at lifecycle timestamps
```

Billing is provider-agnostic. Providers report normalized actual `cost_usd`
when available. `ProviderOutputService` creates one debit using actual cost when
non-zero, otherwise `AI Provider Job.estimated_cost_usd`. Failed, cancelled,
expired, and known zero-cost jobs do not create debits.

## Adapter contract test matrix

Every provider adapter must satisfy the shared adapter contract tested by:

```txt
slow_ai/tests/integration/test_provider_adapter_contracts.py
```

The default test suite must not call external providers. Deterministic provider
adapters run by default and exercise the real worker/provider-job path:
provider-job creation before submit, normalized waiting states, poll success,
failed/cancelled/expired terminal states, idempotent asset/debit boundaries,
and safe run status/history/timeline payloads. Real provider adapters such as
WaveSpeed and Replicate must at minimum expose stable provider names, register
through `ProviderRegistry`, return safe cost-estimate metadata, and normalize
success, waiting, failure, and cancellation responses without network calls.
Gated real-provider tests may validate live API behavior only when explicit env
vars and credentials are present.

Adapter contract tests may persist raw request/response/error fields on
`AI Provider Job`, but safe APIs must never return API keys, Authorization or
Bearer values, provider account names, raw provider URLs, `request_json`,
`response_json`, `raw_error_json`, or stack traces. External output URLs are
allowed only as normalized provider outputs that are then materialized as
`AI Asset` records and exposed through the safe asset/view path.

## Safe observability

Provider job records may persist raw request, response, external job ids, raw
errors, and provider account links server-side for audit and worker execution.
Safe read APIs may expose only display summaries: local provider job name,
provider, model, status, related node run, lifecycle timestamps, poll-attempt
metadata, safe cost fields, and sanitized message/code fields. Public and
Canvas clients must not receive provider account names, external provider job
ids, request_json, response_json, raw_error_json, raw provider URLs,
Authorization headers, API keys, or secrets.

Guest shared-run payloads are stricter than authenticated project reads. They
must not expose provider job observability or source identifiers such as
`source_provider_job`; selected output assets are shown only through the safe
shared asset view path.

System Manager admin observability may expose aggregate provider-job health and
safe local job identifiers, but it must not expose provider account names,
provider account fields, external provider job ids, raw request/response/error
JSON, raw provider URLs, API keys, Authorization headers, stack traces, or
provider secrets. These admin reads are System Manager-only and read-only.

## Timeout and retry policy

Provider polling is bounded by persisted `AI Provider Job` policy fields.
`workers/poll_provider_job.py` increments `poll_attempts`, writes
`last_polled_at`, and stops polling when `poll_attempts >= max_poll_attempts`
or when `submitted_at + timeout_seconds` has passed. Expired jobs are marked
`EXPIRED`, their waiting node run is marked `FAILED` with a safe structured
error, and the parent workflow run is marked `EXPIRED` or `FAILED` depending on
the current workflow state.

Automatic provider retry is not enabled by default. `retry_count` and
`max_retries` are persisted so future retry actions can be explicit and
bounded. No worker may retry forever or create unbounded provider-job rows for
the same node/run idempotency key.

The current polling policy has no time-based backoff window beyond the bounded
`max_poll_attempts` and `timeout_seconds` guards. If an eligible submitted or
waiting provider job is polled repeatedly, each worker invocation may record one
poll attempt until the persisted max-attempt or timeout policy expires the job.
Future backoff support must be persisted and tested as a provider-job policy
field; it must not live in process memory.

Terminal provider jobs are never externally polled again. A terminal provider
job may be reconciled from persisted `response_json` only when its node run is
still `WAITING_PROVIDER`, but that recovery path must not call the provider,
create duplicate assets, create duplicate ledger rows, or enqueue duplicate
resume jobs.

## Normalized provider result

```json
{
  "status": "SUCCEEDED",
  "external_job_id": "provider-job-id",
  "outputs": [
    {
      "asset_type": "VIDEO",
      "url": "https://provider/output.mp4",
      "mime_type": "video/mp4",
      "metadata": {}
    }
  ],
  "cost_usd": 0.0,
  "error": null
}
```

## Forbidden patterns

```txt
if provider == "wavespeed" inside engine
if provider == "replicate" inside engine
provider-specific conditionals inside engine
Provider API calls inside client JS
Provider API calls inside DocType controller
Provider raw response passed directly to UI
Generated output without AI Asset
External call without AI Provider Job
Provider account secret in client code
```

## BYOK provider accounts

`AI Provider Account` records may store user/project-scoped provider keys in the
`api_key_secret` Password field. Account CRUD APIs return only safe metadata:
provider, account label, status, default flag, project, user, owner, creation,
and modified timestamps.

Project-scoped provider account CRUD requires project provider-account
management access: project owner, OWNER member, BILLING member, or System
Manager. EDITOR, VIEWER, non-member, Guest, and DISABLED members are rejected.
For project-scoped accounts, record ownership or user scope does not bypass the
current project membership policy.

Provider account create/default/disable actions use existing Frappe audit
surfaces (`owner`, `creation`, `modified`, `modified_by`, and change tracking
where the persistence path supports it). Rejected account actions must not
create provider jobs, workflow/run records, assets, ledger rows, shares, or call
providers.

Run preflight and provider job persistence both enforce:

```txt
configured account exists
configured account is ACTIVE
configured account belongs to the selected provider
configured account is allowed for the workflow project and current user
default account is ACTIVE and allowed for the workflow project and current user
```

Provider adapters receive only the resolved `AI Provider Job`; they read
credentials server-side from the resolved `provider_account`. Provider account
CRUD and preflight must not call providers.

## Provider/model compatibility

Run preflight is the authoritative compatibility gate before queueing a
provider-node workflow. It must reject before creating `AI Workflow Version`,
`AI Workflow Run`, `AI Node Run`, `AI Provider Job`, `AI Asset`, `AI Credit
Ledger` reservation rows, shares, or worker enqueue when:

```txt
node config provider does not match the selected AI Model provider
AI Model is disabled
AI Model category is not provider
AI Model node_type does not match the provider node type
known-pricing policy is enabled and pricing is unknown
configured provider account belongs to another provider
configured provider account is inactive
configured provider account is outside project/user scope
no active default account is available for the provider
project balance/quota policy rejects the estimated cost
```

Positive preflight may create only the immutable workflow version, workflow
run, node runs, and estimated `RESERVE` ledger rows. `AI Provider Job` records
are created later by the worker/provider node path, immediately before submit.
Preflight denial messages must be safe: no provider secrets, provider account
document names, raw provider URLs, raw request/response/error JSON, API keys,
Authorization headers, stack traces, or workflow draft internals.
