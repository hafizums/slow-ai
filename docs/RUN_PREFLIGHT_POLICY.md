# Run Preflight Policy

## Purpose

`slow_ai` validates provider spend and provider readiness before a workflow run
is persisted or enqueued.

The preflight runs inside `slow_ai.application.run_preflight` after workflow
graph validation and before creating:

```txt
AI Workflow Version
AI Workflow Run
AI Node Run
AI Provider Job
```

## Scope

Preflight checks provider nodes only. Non-provider workflows continue through
the normal `start_run` path.

Provider-node checks resolve:

```txt
provider
model by AI Model name, model_id, or model_slug
enabled AI Model
provider-owned model metadata
provider-node compatible model node_type/category
pricing_json summary
active default or configured AI Provider Account
provider account belongs to the selected provider
provider account is allowed for the workflow project and current user scope
estimated workflow provider cost
current AI Credit Ledger project balance
```

## Rejection Rules

`start_run` is rejected before enqueue when:

```txt
selected model is missing
selected model is disabled
selected model belongs to a different provider
selected model has a non-provider category
selected model node_type does not match the provider node type
configured provider account is missing or inactive
configured provider account belongs to a different provider
configured provider account is scoped to another project or user
no active default provider account exists when node config omits provider_account
no active default provider account is allowed for the workflow project/user scope
pricing is missing while strict pricing is enabled
estimated provider cost exceeds configured budget
estimated provider cost exceeds available project credit balance
```

Rejected preflight must not call providers, create provider jobs, create run
records, create assets, or write credit ledger rows.

## Configuration

Frappe site config keys:

```txt
slow_ai_run_preflight_require_known_pricing
  default: true
  when true, provider models must have known pricing_json

slow_ai_run_preflight_max_cost_usd
  default: unset
  when set, the summed provider-node estimated cost must not exceed this USD value
```

Pricing is read from `AI Model.pricing_json`. Recognized price keys:

```txt
test_cost_usd
amount_usd
base_price
price_usd
```

The same parser in `slow_ai.application.models.pricing_summary_from_json` powers
both public model metadata APIs and run preflight budget checks. Do not duplicate
pricing-key logic in DocType controllers, provider adapters, or client assets.
Model catalog admin APIs may update persisted `AI Model` status, pricing, and
metadata, but preflight remains authoritative and re-reads persisted model
records before any run/version/node/provider-job/queue side effects are created.

After a run passes preflight, provider-node execution persists the resolved
model estimate on `AI Provider Job.estimated_cost_usd` before external submit.
Provider output materialization uses actual normalized provider cost first and
falls back to that persisted estimate when a provider succeeds without returning
actual cost.

## Boundary Rules

Preflight must not import provider adapters, provider registries, workers, or
engine execution code. It reads persisted Frappe metadata only.

Provider API calls remain in `providers/` and happen only during worker-driven
node execution after a run has passed preflight.

The public Tool Run page (`/app/slow-ai-tools`) uses the same `start_run` path
as the admin canvas Tool Mode. It may create and save an editable draft from a
published template, but provider-node runs still pass through this preflight
before any version/run/node/provider-job/queue side effects are created.

Credit balance checks use `slow_ai.application.billing` and persisted
`AI Credit Ledger` rows. Available balance includes active reservations:

```txt
CREDIT + ADJUSTMENT + RELEASE - DEBIT - RESERVE
```

A provider-node run with a non-zero estimated cost must have enough project
available credit balance before `start_run` creates any workflow version, run,
node run, provider job, asset, ledger row, or queue entry. After preflight and
run/node creation, `start_run` reserves the estimate in `AI Credit Ledger`
before enqueue. If reservation creation cannot be completed, the run is not
enqueued.

Provider node execution persists the resolved `AI Provider Account` and resolved
`AI Model` document name on `AI Provider Job`, along with the model-derived
estimated cost. This keeps provider adapters replaceable while preserving link
integrity for model/account/billing records.

The same checks apply to every provider registered in
`ProviderRegistry`, including WaveSpeed and Replicate. Adding a provider must
not add provider-specific branches to preflight or engine code.

BYOK provider accounts are resolved from `AI Provider Account` records only on
the server. Account APIs expose safe metadata and write secrets to the Password
field, but preflight reads no secret value and makes no provider calls.
