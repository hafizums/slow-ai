# WaveSpeed Provider Design

## Purpose

WaveSpeed is the first provider adapter for `slow_ai`.

## Location

```txt
providers/wavespeed/
├── client.py
├── adapter.py
├── auth.py
├── normalizer.py
├── models.py
└── errors.py
```

Generic persistence for provider jobs lives in:

```txt
infrastructure/provider_jobs.py
```

## Rules

WaveSpeed logic must not appear in:

```txt
engine/
doctype/
client JS
generic application services
node_registry except generic provider-node config
```

## Model catalog

Use `AI Model` records for WaveSpeed models. The `model_id` value is the
WaveSpeed REST model path sent to `POST /{model-id}`.

WaveSpeed model rows may also define:

```txt
model_slug
model_name
status
node_type
category
modality
pricing_json
capabilities_json
input_metadata_json
output_metadata_json
```

Provider nodes may reference the model by `AI Model.name`, `model_id`, or
`model_slug`. Generic provider job persistence resolves those references to the
`AI Model` document name before creating `AI Provider Job`; the WaveSpeed
adapter then resolves the document name to the WaveSpeed REST model path before
submitting to WaveSpeed. Client JavaScript must not call WaveSpeed or receive
provider secrets.

`slow_ai.providers.wavespeed.models.upsert_wavespeed_model_catalog` seeds known
WaveSpeed catalog records without making provider calls. It seeds
`wavespeed-ai/flux-dev` as an enabled text-to-image provider model with known
test pricing and seeds `wavespeed-ai/z-image/turbo` as disabled with unknown
pricing. Enable and price that model explicitly before using it in paid runs.

## Provider job invariant

Create `AI Provider Job` before external submit.

## Runtime lifecycle

```txt
ProviderJobRequest
-> AI Provider Job QUEUED
-> AI Provider Job SUBMITTING
-> WaveSpeed POST /{model-id}
-> normalized status and external_job_id
-> AI Provider Job SUBMITTED or FAILED
-> worker/API poll uses GET /predictions/{task-id}/result
-> AI Provider Job WAITING_PROVIDER, SUCCEEDED, FAILED, CANCELLED, or EXPIRED
```

The adapter reads credentials only from the resolved server-side
`AI Provider Account` Password field. Direct server-side adapter tests and
administrative scripts may still fall back to `WAVESPEED_API_KEY` when no
provider account is supplied, but workflow execution should pass through run
preflight and persist the resolved account on `AI Provider Job` before submit.
Client JavaScript must never receive the provider API key.

Provider-node execution persists the active default or configured
`AI Provider Account` on `AI Provider Job.provider_account` before WaveSpeed
submit. Run preflight rejects missing, inactive, provider-mismatched, or
project/user-disallowed accounts before enqueue.

BYOK WaveSpeed accounts are created through `slow_ai.api.provider_accounts.*`
methods. Those methods store the key in `AI Provider Account.api_key_secret` and
return safe metadata only; they do not call WaveSpeed.

WaveSpeed responses are normalized before leaving `providers/wavespeed`.
Provider output URLs are mapped to `NormalizedProviderOutput` asset types that
fit `AI Asset` values: `IMAGE`, `VIDEO`, `AUDIO`, `JSON`, or `TEXT`.

## Provider test env vars

```bash
SLOW_AI_REAL_PROVIDER_TESTS=1
WAVESPEED_API_KEY=...
SLOW_AI_REAL_PROVIDER_TEST_BUDGET_USD=0.02
SLOW_AI_REAL_PROVIDER_POLL_TIMEOUT_SECONDS=180
SLOW_AI_REAL_PROVIDER_POLL_INTERVAL_SECONDS=3
```

The normal integration suite uses real Frappe DocTypes and an injected
deterministic transport to prove provider job lifecycle behavior without
performing an external provider call.

The gated real provider suite lives in:

```txt
slow_ai/tests/integration/test_real_wavespeed_provider.py
```

It seeds or loads an enabled local `AI Model` for `wavespeed-ai/flux-dev`, then
selects the cheapest enabled WaveSpeed text-to-image model with known
`pricing_json`. The suite refuses to submit if no model has known pricing or if
the selected model price exceeds `SLOW_AI_REAL_PROVIDER_TEST_BUDGET_USD`.

The real suite creates a server-side `AI Provider Account`, starts a persisted
workflow run through the normal application and worker path, verifies
`AI Provider Job` exists before WaveSpeed submit, polls until terminal state,
materializes successful outputs into `AI Asset`, creates `AI Credit Ledger` only
when the provider reports non-zero cost, and exposes the result through run
history. It also covers the invalid API key path without creating assets or
ledger rows.
