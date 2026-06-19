# Replicate Provider Design

## Purpose

Replicate is the first real second provider adapter for `slow_ai`. It proves the
provider registry, model catalog, BYOK account handling, run preflight, billing,
and provider output materialization work beyond WaveSpeed.

## Choice

Replicate was selected because its HTTP predictions API maps cleanly to the
existing provider lifecycle:

```txt
create prediction
poll prediction by id
cancel prediction by id
normalize output URLs or data URLs
```

It also supports user-owned API tokens, which fits the existing BYOK
`AI Provider Account` model.

## Location

```txt
providers/replicate/
├── client.py
├── adapter.py
├── auth.py
├── normalizer.py
├── models.py
└── errors.py
```

## Rules

Replicate logic must not appear in:

```txt
engine/
doctype/
client JS
generic application services
node_registry except generic provider-node config
```

## Model Catalog

`slow_ai.providers.replicate.models.upsert_replicate_model_catalog` seeds one
safe text-to-image model record without provider calls:

```txt
provider: replicate
model_id: black-forest-labs/flux-schnell
model_slug: replicate-flux-schnell
node_type: provider_text_to_image
category: provider
modality: TEXT_TO_IMAGE
```

The seeded `pricing_json` contains a conservative `test_cost_usd` used by run
preflight and gated real-provider spending guards. Verify current provider
billing before using the seeded price for production charging.

ProviderJob creation persists that parsed estimate on
`AI Provider Job.estimated_cost_usd` before Replicate submission.

## Provider Job Lifecycle

```txt
ProviderJobRequest
-> AI Provider Job QUEUED
-> AI Provider Job SUBMITTING
-> Replicate POST /predictions
-> normalized status and prediction id
-> AI Provider Job SUBMITTED, WAITING_PROVIDER, SUCCEEDED, or FAILED
-> worker/API poll uses GET /predictions/{prediction_id}
-> AI Provider Job SUCCEEDED, FAILED, or CANCELLED
```

The adapter reads credentials only from the resolved server-side
`AI Provider Account` Password field. Direct server-side adapter tests and
administrative scripts may also fall back to `REPLICATE_API_KEY` or
`REPLICATE_API_TOKEN` when no provider account is supplied. Client JavaScript
must never receive Replicate API keys.

## Normalization

Replicate responses are normalized before leaving `providers/replicate`.
Supported output forms:

```txt
URL string
data URL string
object with url/uri/href and mime metadata
list of any of the above
```

Image outputs are materialized through the existing `AI Asset` path. Non-zero
normalized actual cost creates one idempotent `AI Credit Ledger` debit through
the generic provider output service. Replicate may omit actual cost from a
successful prediction response; in that case materialization uses the persisted
ProviderJob estimate and records `debit_cost_source = ESTIMATED`. Known
zero-cost models create no debit, and failed/cancelled Replicate jobs create no
asset or debit.

## Provider Test Env Vars

```bash
SLOW_AI_REAL_REPLICATE_TESTS=1
REPLICATE_API_KEY=...
SLOW_AI_REAL_REPLICATE_TEST_BUDGET_USD=0.01
SLOW_AI_REAL_REPLICATE_POLL_TIMEOUT_SECONDS=180
SLOW_AI_REAL_REPLICATE_POLL_INTERVAL_SECONDS=3
```

The normal integration suite uses real Frappe DocTypes and a recording transport
at the outbound HTTP boundary. It does not spend real provider credits.

The gated real provider suite lives in:

```txt
slow_ai/tests/integration/test_real_replicate_provider.py
```
