# Billing and Cost Ledger

## Core rule

Every cost or credit movement must create `AI Credit Ledger`.

## Ledger policy

Append-only.

The ledger is the source of truth for project credit balance.

## Entry types

```txt
CREDIT
RESERVE
RELEASE
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
available_balance_usd = CREDIT + ADJUSTMENT + RELEASE - DEBIT - RESERVE
```

`slow_ai.application.billing.get_balance` returns project totals. Passing a
`user` filters ledger rows by owner inside the same project for user-scoped
display. Run preflight enforces project balance for provider-node workflows.

Daily spend caps are separate from current available balance. Run preflight
calculates current-day spend exposure from persisted ledger rows:

```txt
daily_spend_exposure = DEBIT + RESERVE - RELEASE
```

This keeps active reservations inside the cap until they settle, then leaves
only the final debit as daily spend.

Before a provider-node workflow with non-zero estimated cost is enqueued:

```txt
slow_ai.application.run_preflight
  -> resolve provider/model/pricing/account
  -> sum estimated provider cost
  -> compare with slow_ai.application.billing project balance
```

If the estimate exceeds available balance, `start_run` rejects before creating
workflow versions, workflow runs, node runs, provider jobs, assets, ledger rows,
or queue jobs. Balance checks read persisted ledger data only and do not call
providers.

If adding the new estimated cost would exceed `AI Project` daily project or
daily user spend caps, `start_run` rejects at the same preflight boundary and
does not create reservations.

After preflight passes and the immutable workflow/run/node rows exist,
`start_run` creates one `RESERVE` row per priced provider node before enqueue.
Reservation rows link to project, workflow run, node run, and model metadata.
When the provider job is later created, the reservation is linked to the
`AI Provider Job` as enrichment metadata. Duplicate `start_run` or worker
retries must reuse existing reservation rows.

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

The API is restricted by project billing policy: project owner, OWNER member,
BILLING member, or System Manager. EDITOR, VIEWER, non-member, Guest, and
DISABLED members are rejected before ledger or execution side effects. A
successful top-up creates exactly one `CREDIT` row and returns a safe ledger
payload plus current balance.

Top-ups are audited through the append-only `AI Credit Ledger` business record
and normal Frappe `owner`, `creation`, `modified`, and `modified_by` fields.
Rejected top-up attempts must not create ledger rows, workflow/run/node/
provider/asset/share records, enqueue workers, or call providers.

Read APIs:

```txt
slow_ai.api.billing.get_balance
slow_ai.api.billing.get_ledger
```

These APIs return safe accounting fields only. They must not expose provider
account secrets, raw provider responses, provider credentials, or provider
adapter internals.
Balance and ledger reads are read-only and use the same project billing-view
policy. Allowed reads create or mutate no workflow, run, node, provider job,
asset, ledger, or share records.

## Task 09 implementation

Provider output cost ledger creation is centralized in:

```txt
slow_ai/infrastructure/provider_outputs.py
  CreditLedgerService.create_provider_debit()
  ProviderOutputService.materialize()
```

Rules:

```txt
Create at most one RESERVE ledger row for each priced provider node run before enqueue.
Create at most one DEBIT ledger row for a successful provider job.
Create at most one RELEASE ledger row for each reservation when the job/run settles.
Link provider debits to AI Project, AI Workflow Run, AI Node Run, and AI Provider Job.
Use the normalized provider result cost_usd as the actual provider cost when it is non-zero.
If actual cost is zero or unavailable, use AI Provider Job.estimated_cost_usd.
If both actual and estimated cost are zero for a known zero-cost model, create no DEBIT.
If cost is unknown at materialization time, refuse to materialize the output instead of silently creating an unpaid asset.
If actual cost exceeds the reservation, allow only the extra amount that fits current available balance.
Keep billing provider-agnostic; ledger rows link to `AI Provider Job` and use
normalized provider results plus persisted ProviderJob estimate fields instead of provider-specific response fields.
Do not create duplicate provider debits when a provider job is polled more than once.
Do not create duplicate provider releases when a provider job is polled, cancelled, or timed out more than once.
Do not create final DEBIT rows for failed, cancelled, expired, or known zero-cost provider results.
```

`AI Provider Job.debit_cost_source` records whether a debit came from
`ACTUAL`, `ESTIMATED`, or `ZERO_COST`, and `debit_cost_usd` records the amount
used for run history display.

`RELEASE` offsets the reservation hold. On successful settlement, the full
reservation is released and the final `DEBIT` records the actual or estimated
provider cost. The unused available credit restored by settlement is therefore
`RESERVE - DEBIT` when the debit is lower than the reservation. On provider
failure, timeout, expiry, cancellation, or workflow failure before provider
completion, the reservation is released and no output asset/final debit is
created unless a future explicit policy records a real provider charge.

## Reservation reconciliation boundary

Reservation reconciliation is allowed only in mutating service/worker paths that
already own run or provider-job state transitions:

```txt
start_run -> create RESERVE
provider output materialization -> create/reuse DEBIT and RELEASE
provider failed/cancelled/expired poll handling -> RELEASE
workflow failed/cancelled/expired terminal transition -> RELEASE
System Manager recovery expiry -> RELEASE
```

Read APIs such as `get_balance`, `get_ledger`, run status/history/timeline,
output gallery, asset view, and shared-run reads must not perform reconciliation
or create missing release/debit rows. A terminal run should have no active
unreleased reservation unless a future policy explicitly records an outstanding
provider charge and documents it. Reconciliation rows are idempotent by
workflow run, node run, provider job, and reservation reference.

Repeated provider poller, resume worker, cancellation, timeout, expiry, and
System Manager recovery invocations must not create duplicate `DEBIT` or
`RELEASE` rows. A repeated successful provider poll reuses the existing provider
assets and provider-job `DEBIT`; a repeated failed/cancelled/expired provider
poll or stale-run expiry reuses the existing release for the original
reservation.
