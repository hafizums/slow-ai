# Admin Safe Observability Contract

System Manager observability APIs provide safe operational summaries for Slow AI
without exposing provider secrets or raw provider payloads.

Allowed APIs:

```txt
slow_ai.api.admin.get_system_overview
slow_ai.api.admin.list_run_health
slow_ai.api.admin.list_provider_job_health
slow_ai.api.admin.list_billing_health
```

All API methods are thin delegates to `slow_ai.application.admin_observability`.
The application service enforces System Manager access. Project owners,
members, non-members, and Guest users must be denied.

The APIs are read-only. Calling them must not create, update, delete, enqueue,
or mutate:

- `AI Workflow Version`
- `AI Workflow Run`
- `AI Node Run`
- `AI Provider Job`
- `AI Asset`
- `AI Credit Ledger`
- `AI Tool Run Share`

Safe payloads may include aggregate counts, statuses, project identifiers,
workflow run identifiers, provider names, model identifiers, timestamps, poll
attempt counts, and safe billing totals. Payloads must not include provider
account names, provider account fields, API keys, Authorization headers, raw
provider URLs, `request_json`, `response_json`, `raw_error_json`,
`external_job_id`, stack traces, or provider secrets.

The System Manager Desk page lives at:

```txt
/app/slow-ai-admin
```

The page may call only the four admin observability APIs listed above. It must
not call providers, worker/recovery APIs, raw payload APIs, `frappe.db`,
`frappe.enqueue`, or any non-admin `slow_ai` API. The page is read-only:
opening, refreshing, and filtering must not create or mutate workflow,
provider, asset, ledger, model, account, template, or share records.

The page renders these safe sections:

- run status counts and stale waiting-provider count
- provider job status counts and stale waiting-provider count
- billing totals
- model, provider account, and share status counts
- recent run health rows
- recent provider-job health rows
- project billing health rows

System Managers and Administrator may view the page. Non-System Manager users
may open the route but must see a generic unavailable state and no admin
controls. Section loading, empty, and failure states must be generic and safe:
they must not render raw server responses, tracebacks, provider account names,
provider secrets, raw provider URLs, API keys, Authorization headers,
`request_json`, `response_json`, `raw_error_json`, or workflow draft internals.

Nearby operational panels in Canvas and Public Tool pages keep their own
generic empty/error states for Model Catalog, Provider Accounts, Billing
balance, My Runs, Timeline, and Asset Gallery. Those states must stay
display-only and must not auto-create records, call providers, enqueue workers,
or render raw server errors.

Canvas, Public Tool, and guest shared pages must not call `slow_ai.api.admin.*`.

Coverage lives in:

```txt
slow_ai/tests/integration/test_admin_safe_observability.py
slow_ai/tests/integration/test_admin_observability_page.py
apps/slow_ai/e2e/slow_ai_canvas.spec.js
```
