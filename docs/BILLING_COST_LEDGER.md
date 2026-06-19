# Billing and Cost Ledger

## Core rule

Every cost or credit movement must create `AI Credit Ledger`.

## Ledger policy

Append-only.

The ledger is the source of truth for project credit balance.

## Entry types

```txt
CREDIT
DEBIT
ADJUSTMENT
```

## Required links

Ledger entries should link to:

```txt
AI Project
AI Workflow Run
AI Node Run
AI Provider Job
```

## Cost calculation policy

Do not duplicate pricing logic.

Use:

```txt
AI Model.pricing_json
ProviderAdapter.estimate_cost()
Provider actual cost when available
AI Provider Job.estimated_cost_usd when actual cost is unavailable
```

## Balance policy

Project balance is calculated from real `AI Credit Ledger` rows:

```txt
balance_usd = CREDIT + ADJUSTMENT - DEBIT
```

`slow_ai.application.billing.get_balance` returns project totals. Passing a
`user` filters ledger rows by owner inside the same project for user-scoped
display. Run preflight enforces project balance for provider-node workflows.

Before a provider-node workflow with non-zero estimated cost is enqueued:

```txt
slow_ai.application.run_preflight
  -> resolve provider/model/pricing/account
  -> sum estimated provider cost
  -> compare with slow_ai.application.billing project balance
```

If the estimate exceeds balance, `start_run` rejects before creating workflow
versions, workflow runs, node runs, provider jobs, assets, ledger rows, or queue
jobs. Balance checks read persisted ledger data only and do not call providers.

When execution later creates an `AI Provider Job`, the same model-pricing parser
persists `estimated_cost_usd` before submit. This gives the output
materialization path a provider-agnostic fallback when a provider succeeds but
does not return actual cost.

## Top-up policy

Admin credit top-ups create append-only `AI Credit Ledger` rows:

```txt
slow_ai.application.billing.create_top_up()
slow_ai.api.billing.create_top_up()
```

The API is restricted to `System Manager`, creates a `CREDIT` row, and returns a
safe ledger payload plus current balance.

Read APIs:

```txt
slow_ai.api.billing.get_balance
slow_ai.api.billing.get_ledger
```

These APIs return safe accounting fields only. They must not expose provider
account secrets, raw provider responses, provider credentials, or provider
adapter internals.

## Task 09 implementation

Provider output cost ledger creation is centralized in:

```txt
slow_ai/infrastructure/provider_outputs.py
  CreditLedgerService.create_provider_debit()
  ProviderOutputService.materialize()
```

Rules:

```txt
Create at most one DEBIT ledger row for a successful provider job.
Link provider debits to AI Project, AI Workflow Run, AI Node Run, and AI Provider Job.
Use the normalized provider result cost_usd as the actual provider cost when it is non-zero.
If actual cost is zero or unavailable, use AI Provider Job.estimated_cost_usd.
If both actual and estimated cost are zero for a known zero-cost model, create no DEBIT.
If cost is unknown at materialization time, refuse to materialize the output instead of silently creating an unpaid asset.
Keep billing provider-agnostic; ledger rows link to `AI Provider Job` and use
normalized provider results plus persisted ProviderJob estimate fields instead of provider-specific response fields.
Do not create duplicate provider debits when a provider job is polled more than once.
Do not create ledger rows for failed, cancelled, expired, or known zero-cost provider results.
```

`AI Provider Job.debit_cost_source` records whether a debit came from
`ACTUAL`, `ESTIMATED`, or `ZERO_COST`, and `debit_cost_usd` records the amount
used for run history display.
