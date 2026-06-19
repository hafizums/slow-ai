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
submitted_at and completed_at lifecycle timestamps
```

Billing is provider-agnostic. Providers report normalized actual `cost_usd`
when available. `ProviderOutputService` creates one debit using actual cost when
non-zero, otherwise `AI Provider Job.estimated_cost_usd`. Failed, cancelled,
expired, and known zero-cost jobs do not create debits.

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
