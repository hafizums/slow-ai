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

Canvas, Public Tool, and guest shared pages must not call `slow_ai.api.admin.*`.
Admin observability has no frontend surface in this milestone.

Coverage lives in:

```txt
slow_ai/tests/integration/test_admin_safe_observability.py
```
