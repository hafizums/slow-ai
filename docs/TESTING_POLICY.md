# Testing Policy

## Core rule

No mock-based acceptance tests.

## Allowed

```txt
Real Frappe test site
Real DocType inserts
Real test fixtures
Real factories that create actual documents
Real API method calls
Real worker code execution
Real file creation
Real browser interactions against Frappe Desk
Real provider tests when env vars are enabled
```

## Not accepted as acceptance proof

```txt
Mock provider success
Mock database writes
Mock DocType insert
Mock worker execution
Frontend-only fake success
Provider response hardcoded as final proof
```

## Required integration tests

```txt
test_platform_kernel_creates_real_documents
test_start_run_creates_immutable_workflow_version
test_graph_validation_rejects_cycle
test_unknown_node_type_is_rejected
test_node_runs_created_for_all_nodes
test_provider_job_created_before_external_call
test_asset_created_for_provider_output
test_credit_ledger_created_for_cost
test_run_history_returns_node_provider_asset_records
test_no_local_model_nodes_are_registered
test_architecture_boundaries
test_private_workspace
test_real_wavespeed_provider_gated
test_run_preflight
test_model_catalog_admin
test_billing_credit_balance
test_multi_provider_foundation
test_provider_account_byok
test_provider_replicate
test_real_replicate_provider_gated
test_public_tool_page
test_tool_run_sharing
```

Task 01 starts the real integration test package with:

```txt
slow_ai/tests/integration/test_platform_kernel.py
```

The kernel test uses Frappe's real test runner and concrete test node
definitions. It does not use mock-based acceptance proof and does not call
external providers.

Task 02 adds real DocType insertion coverage with:

```txt
slow_ai/tests/integration/test_core_doctypes.py
```

This test inserts real `AI Project`, workflow, run, node run, provider job,
asset, ledger, model, provider account, and template documents. It does not mock
database writes or provider calls.

Task 03 adds workflow JSON and node registry coverage with:

```txt
slow_ai/tests/integration/test_workflow_json_and_node_registry.py
```

This test validates real node registry metadata, the whitelisted object_info API
method, and workflow JSON validation behavior. It does not mock registered
nodes, API calls, or graph validation.

Task 04 adds engine core coverage with:

```txt
slow_ai/tests/integration/test_engine_core.py
```

This test creates real workflow documents, starts real runs through the
application service, executes the real DAG runner, and asserts persisted
workflow/node run state. It does not mock DocType inserts, node execution, or
worker behavior.

Task 05 adds provider base and WaveSpeed coverage with:

```txt
slow_ai/tests/integration/test_provider_wavespeed.py
```

This test creates real `AI Model`, `AI Provider Account`, and `AI Provider Job`
documents, verifies a provider job exists before the outbound WaveSpeed submit
boundary is invoked, persists submit and poll results, and checks server-side
secret access. The normal suite does not spend real provider credits.

Task 06 adds provider node coverage with:

```txt
slow_ai/tests/integration/test_provider_nodes.py
```

This test executes a real persisted workflow through `RunService` and
`WorkflowExecutor` with generic provider nodes. It asserts real `AI Provider
Job`, `AI Asset`, `AI Credit Ledger`, and `AI Node Run.provider_job`
persistence. It uses a deterministic provider adapter inside the provider
contract boundary and does not make external provider calls in the normal suite.

Task 07 adds API method coverage with:

```txt
slow_ai/tests/integration/test_api_methods.py
```

This test calls whitelisted methods through `frappe.call`, creates real workflow
drafts, starts real queued runs, checks queue/status/history payloads, and
creates real `AI Asset` records through the upload/view API. It asserts that
`start_run` queues work instead of executing the workflow inline.

Task 08 adds worker and realtime coverage with:

```txt
slow_ai/tests/integration/test_workers_realtime.py
```

This test creates real persisted workflow/run/node/provider-job documents,
invokes worker entrypoints directly, and verifies persisted state plus Frappe
realtime log entries emitted by the real `frappe.publish_realtime` path. It
also exercises the scheduled provider polling batch entrypoint against real
`AI Provider Job` rows and verifies that only submitted/waiting jobs with an
external job id are polled.

Task 09 adds asset and ledger pipeline coverage with:

```txt
slow_ai/tests/integration/test_asset_ledger_pipeline.py
```

This test runs a real persisted workflow to `WAITING_PROVIDER`, polls a real
provider job through the worker entrypoint, verifies idempotent `AI Asset` and
`AI Credit Ledger` creation, and resumes the workflow from persisted provider
outputs. It uses a deterministic provider adapter inside the provider contract
boundary and does not make external provider calls in the normal suite.

Run idempotency and recovery coverage lives in:

```txt
slow_ai/tests/integration/test_run_idempotency_recovery.py
```

This test creates real workflows, runs, node runs, provider jobs, provider
accounts, assets, and ledger rows. It verifies duplicate `start_run` calls reuse
a recent active run for an unchanged draft, worker/node/resume retries do not
duplicate side-effect records, provider-node retries reuse the provider-job
idempotency key, repeated provider polling creates no duplicate assets or
debits, terminal runs remain terminal, and public run detail payloads do not
expose raw provider request/response/error data or provider account names.

Provider job timeout and retry policy coverage lives in:

```txt
slow_ai/tests/integration/test_provider_job_timeout_retry_policy.py
```

This test creates real workflows, node runs, provider jobs, provider accounts,
models, and credit rows, then invokes the real provider poll worker. It verifies
max-poll-attempt expiration, timeout expiration before provider polling, safe
node/workflow timeout errors, no asset/ledger/resume side effects after expiry,
cancellation winning over timeout policy, and public run detail payloads hiding
raw provider response/error data, provider account names, secrets, and raw
provider URLs.

Task 10 adds canvas placeholder coverage with:

```txt
slow_ai/tests/integration/test_canvas_placeholder.py
```

This test reloads the real Frappe Desk Page, verifies its page assets are loaded
through Frappe's Page loader, checks that the client script references only the
allowed `slow_ai` API methods, and exercises the save/start/status/history/queue
API flow with real persisted documents. It also verifies the placeholder
provider-node starter graph and the asset output panel path through
`slow_ai.api.assets.view`. The canvas safety coverage verifies that provider-node
graphs show the explicit external-provider credit warning, display unknown-cost
fallback text, keep `start_run` as the backend execution API, and expose no
provider URLs or secrets in client assets. The metadata palette coverage
verifies that the page uses `object_info` schema metadata for node categories,
schema summaries, and the `Add Node` draft action, while provider-node starts
still rely on backend run preflight. The graph editor coverage verifies that
config controls are generated from `object_info`, node/edge edit operations
mutate draft JSON only, save/start still use the backend APIs, and invalid
graphs are rejected by backend validation rather than silently accepted by the
client. The run monitor coverage verifies that the client references only
allowed `slow_ai` APIs, subscribes to the existing realtime event names, uses
`get_run_status` and `get_history` for persisted execution state, uses
`slow_ai.api.assets.view` for asset links, renders ledger/cost summaries from
history data, and exposes only sanitized error display in client assets.
The asset preview coverage verifies that the canvas represents image, video,
audio, JSON, and text preview paths from `slow_ai.api.assets.view` payloads,
renders persisted source metadata, and keeps all asset links API-derived.
The template library coverage verifies that the canvas references only the
allowed template APIs, lists real templates, saves the current draft graph as a
real `AI Workflow Template`, creates an editable `AI Workflow` draft from a
template, and does not create workflow runs, immutable workflow versions,
	provider jobs, workers, or provider calls during template actions.
Template publish review coverage proves owners can submit draft/rejected
templates for review, System Managers can approve/reject/archive templates,
public tool APIs expose only `PUBLISHED` templates, publication validation
rejects invalid graph/schema/unsafe provider-target payloads, and review
actions create no `AI Workflow`, `AI Workflow Version`, run, node,
provider-job, asset, or ledger records.
It also proves direct `save_template` calls cannot set `IN_REVIEW`,
`PUBLISHED`, `ARCHIVED`, or newly set `REJECTED`, so System Managers and owners
must use the review APIs for lifecycle transitions.
Template versioning coverage proves approval creates immutable
`AI Workflow Template Version` snapshots, public tool APIs read the active
version instead of mutable template JSON, mutable edits do not leak before a new
approval, rollback creates a new active version from a historical snapshot, and
version/list/rollback actions create no workflow execution/provider/billing
side effects.
	The Tool Mode coverage verifies that the canvas references only allowed
	`slow_ai` APIs, creates an editable draft from a real template, saves form
	values into persisted workflow draft JSON, starts runs only through
	`slow_ai.api.runs.start_run`, and still relies on backend run preflight for
	provider-node templates. The Tool Mode upload coverage verifies that
	`upload_asset` fields can reference real `AI Asset` records, create assets only
	through `slow_ai.api.assets.upload`, preview assets only through
	`slow_ai.api.assets.view`, persist the selected asset name into draft JSON, and
	avoid provider jobs during upload/template/load actions.
	The Model Catalog UI coverage verifies that the canvas references only safe
	`slow_ai.api.models.*` methods, renders safe model list/detail metadata,
	persists status/pricing updates through real `AI Model` records, displays
	disabled/unpriced preflight warnings, and creates no provider jobs or provider
	calls during catalog actions.

Public Tool Page coverage lives in:

```txt
slow_ai/tests/integration/test_public_tool_page.py
```

This test reloads the real `/app/slow-ai-tools` Desk Page, verifies the client
script references only the allowed public tool/workflow/run/asset/billing/model
APIs, verifies only published templates are listed, verifies unpublished
templates are rejected, persists submitted form values into real workflow draft
JSON, starts runs only through the normal run API, verifies insufficient balance
rejects provider templates before ProviderJob creation, verifies rerun
preparation creates a new editable draft from the original recorded immutable
template version while copying only schema-safe prefilled values, verifies rerun
draft edits persist only through schema-allowed backend fields before
`start_run`, verifies historical no-schema rerun edits use only the legacy
public tool allow-list with asset project access checks, and verifies upload
asset inputs and previews use real persisted `AI Asset` records. It
also covers the Tool Run Library by proving normal users see only owned-project
runs, System Managers can see all runs, run detail payloads strip provider
accounts/raw provider payloads/secrets, failed errors are sanitized, asset
previews resolve through the safe run output gallery service, and listing/viewing
runs does not create provider jobs or call providers. Public tool cancellation
coverage proves OWNER/EDITOR users can cancel non-terminal runs, VIEWER/BILLING
users are rejected, terminal runs are rejected, node/provider job rows are
marked only through local persisted state, workers and pollers do not progress
cancelled runs, and cancel actions create no new execution/provider/billing
records.

The Run Output Gallery coverage in the same module proves grouped gallery
payloads are built from real `AI Asset` and `AI Node Run` records, only safe
asset view metadata is returned, provider account names/secrets/raw provider
request/response/error JSON are excluded, VIEWER and EDITOR project members can
view accessible run galleries, nonmembers are rejected, failed/empty runs return
safe empty payloads, guest shared gallery payloads strip project/internal run
metadata from nested `output_gallery.run`, shared flat/grouped gallery assets
remain selected-only, and gallery reads create no provider jobs, assets, ledger
rows, workflow versions, workflow runs, or node runs.

The Tool Run Sharing coverage in the same test module proves normal users can
share selected outputs from their own completed runs, cannot share another
user's project run, System Managers can manage shares, guests can read active
non-expired shares, guests see selected assets but not unselected assets,
empty/unknown/cross-run asset selections are rejected, disabled or expired
shares are rejected, shared payloads strip provider accounts/raw provider
payloads/secrets, and share creation does not create provider jobs, assets,
ledger rows, workflow versions, or workflow runs.

BYOK provider account coverage lives in:

```txt
slow_ai/tests/integration/test_provider_account_byok.py
```

This test uses real `AI Provider Account`, `AI Project`, `AI Model`,
`AI Workflow`, `AI Provider Job`, and ledger documents. It verifies safe
provider account APIs, Password-field secret storage, scoped default/configured
account resolution, preflight rejection before enqueue for inactive/mismatched
or disallowed accounts, persisted `AI Provider Job.provider_account`, and
WaveSpeed server-side credential lookup. Account CRUD and preflight tests do not
call providers.

Provider account UI coverage is part of:

```txt
slow_ai/tests/integration/test_canvas_placeholder.py
apps/slow_ai/e2e/slow_ai_canvas.spec.js
```

The integration test verifies the canvas references only the safe provider
account APIs, uses a password input for account creation, stores the secret only
server-side, lists and fetches safe payloads without secrets, sets defaults,
disables accounts, and proves disabled accounts are rejected by backend
preflight before ProviderJob creation. The browser test drives the real Desk
page to create/list/view/default/disable an account and checks the API key is
not displayed after save.

Task 11 adds tool mode and workflow template coverage with:

```txt
slow_ai/tests/integration/test_tool_mode_design.py
```

This test executes a real persisted workflow with a `tool_output` node and
verifies the persisted node output payload. It also calls real template API
methods to save, list, load, instantiate, and start a workflow created from an
`AI Workflow Template`.

Task 12 adds review and hardening coverage with:

```txt
slow_ai/tests/integration/test_architecture_boundaries.py
```

This test scans the real app files through the Frappe test runner. It verifies
thin API delegates, persistence-only DocType controllers, API-only client
assets, no direct SQL, no production ComfyUI references, and no local model
runtime terms in production code.

Private workspace coverage lives in:

```txt
slow_ai/tests/integration/test_private_workspace.py
```

Model catalog admin coverage lives in:

```txt
slow_ai/tests/integration/test_model_catalog_admin.py
```

This test creates and updates real `AI Model` records, verifies safe model
metadata list/detail APIs, verifies disabled and mismatched models are rejected
by backend run preflight, verifies public metadata and preflight share the same
pricing parser, and verifies WaveSpeed catalog seeding does not create provider
jobs or call providers. It also covers admin status/pricing/metadata update APIs
and proves disabled or unpriced models remain backend preflight failures without
creating ProviderJob records.

Billing credit balance coverage lives in:

```txt
slow_ai/tests/integration/test_billing_credit_balance.py
```

This test creates real `AI Credit Ledger` credit top-ups, calculates balance
from persisted ledger rows, verifies provider runs with sufficient balance pass
preflight, verifies insufficient balance rejects before workflow/run/node/provider
job side effects, verifies provider output debits remain idempotent, verifies
actual-cost debits win over estimates, verifies missing actual cost falls back
to persisted ProviderJob estimates, verifies zero-cost/failed jobs do not debit,
verifies run history exposes ledger and debit source fields safely, and verifies
billing APIs expose no provider secrets.

Billing credit reservation coverage lives in:

```txt
slow_ai/tests/integration/test_billing_credit_reservation.py
```

This test creates real projects, models, provider accounts, workflows, runs,
provider jobs, assets, and `AI Credit Ledger` rows. It verifies insufficient
balance rejects before run/provider/reservation side effects, `start_run`
creates exactly one `RESERVE`, duplicate starts/workers do not duplicate
reservations, provider success creates one `DEBIT` and one `RELEASE`, provider
failure/timeout/cancel releases reservations without output assets or final
debits, repeated poll/cancel/timeout paths do not duplicate release/debit rows,
and public run detail exposes only safe reserve/release/debit summaries without
raw provider payloads or provider account names.

Multi-provider foundation coverage lives in:

```txt
slow_ai/tests/integration/test_multi_provider_foundation.py
```

This test registers multiple deterministic provider adapters through the
provider registry, verifies WaveSpeed remains in the default registry, verifies
generic provider nodes resolve model/account records and debit billing without
engine changes, verifies configured/default provider accounts are persisted on
`AI Provider Job`, and verifies wrong provider/model/account combinations are
rejected before enqueue without provider calls or provider jobs.

This test creates a real private `Workspace` for a system user, verifies that it
appears in that user's Frappe Desk sidebar, and checks that its links remain
navigation-only with no provider secrets or execution logic.

Gated real WaveSpeed coverage lives in:

```txt
slow_ai/tests/integration/test_real_wavespeed_provider.py
```

It is skipped unless both of these are set:

```bash
SLOW_AI_REAL_PROVIDER_TESTS=1
WAVESPEED_API_KEY=...
```

The suite has a spending guard controlled by:

```bash
SLOW_AI_REAL_PROVIDER_TEST_BUDGET_USD=0.02
```

It refuses to submit real provider work when the selected local `AI Model` has
no known `pricing_json` or its known price exceeds the configured test budget.
The default seeded test model is `wavespeed-ai/flux-dev` with a documented base
price of `$0.012` per run.

Replicate provider coverage lives in:

```txt
slow_ai/tests/integration/test_provider_replicate.py
```

This test creates real `AI Model`, `AI Provider Account`, `AI Workflow`,
`AI Provider Job`, `AI Asset`, and `AI Credit Ledger` documents. It verifies
the default registry includes WaveSpeed and Replicate, Replicate catalog seed
metadata is safe, BYOK secret lookup is server-side, ProviderJob exists before
the outbound Replicate submission boundary, provider-node workflows use the
generic provider pipeline, successful no-actual-cost Replicate output debits
from the persisted estimate, bad model/account/provider/balance combinations
are rejected before enqueue, and no real provider credits are spent in the
normal suite.

Gated real Replicate coverage lives in:

```txt
slow_ai/tests/integration/test_real_replicate_provider.py
```

It is skipped unless both of these are set:

```bash
SLOW_AI_REAL_REPLICATE_TESTS=1
REPLICATE_API_KEY=...
```

The suite has a spending guard controlled by:

```bash
SLOW_AI_REAL_REPLICATE_TEST_BUDGET_USD=0.01
```

It refuses to submit real provider work when the selected local `AI Model` has
no known `pricing_json` or its known test price exceeds the configured budget.

## Standard command

```bash
bench --site saas run-tests --app slow_ai
```

## Browser E2E command

```bash
npm run test:e2e
```

Browser E2E coverage lives in:

```txt
apps/slow_ai/e2e/slow_ai_canvas.spec.js
```

The E2E runner uses Playwright against the real Frappe site configured by
`SLOW_AI_E2E_BASE_URL` and `SLOW_AI_E2E_SITE` (`http://127.0.0.1:8001` and
`saas` by default). If the web server is not already running, the runner starts
`bench serve` for the duration of the test.

Browser fixtures are created through:

```txt
slow_ai.tests.e2e.fixtures.setup_canvas_e2e
```

Those fixtures create real users, projects, templates, workflows, runs, and
assets. They do not mock provider success or call external paid providers. Paid
provider execution remains covered only by the gated real WaveSpeed suite.

The browser test verifies that a real user can log into Desk, open
`/app/slow-ai-canvas`, load the `object_info` palette, add and edit draft
nodes, drag visual nodes to update draft layout, delete and create edges
through the visual canvas ports, save a workflow draft with persisted layout,
see paid-provider confirmation before start, render run status/history, render
asset preview cards from persisted history, list templates, inspect the Model
Catalog list/detail warnings from safe APIs, run Tool Mode from a template,
persist Tool Mode form values, and select/create AI Assets through the allowed
asset APIs.

The same browser suite also logs in as a normal Desk user, opens
`/app/slow-ai-tools`, lists published templates through the public tool API,
selects a template, renders typed fields from `input_schema_json`, submits form
values through `slow_ai.api.public_tools.prepare_workflow_from_template`, starts
through `slow_ai.api.runs.start_run`, renders persisted status/history, selects
and uploads `AI Asset` records through the allowed asset APIs, opens the My Runs
library through scoped public tool run APIs, opens a run detail, and renders
grouped output gallery cards from safe backend gallery data, including image,
video, and audio preview branches when fixture assets exist.
It also verifies the Project Members panel uses safe project membership APIs,
an owner can add EDITOR and VIEWER members, an EDITOR can use the same project
through the backend Tool Mode path, and a VIEWER can read project runs but
cannot create a workflow draft or start a run.
The browser suite also submits a draft template for review from the canvas,
approves it as a System Manager, verifies it appears in the public tool page,
and verifies rejected/archived templates remain hidden from the public catalog.

Template input schema coverage lives in:

```txt
slow_ai/tests/integration/test_template_input_schema.py
```

It creates real templates, projects, users, memberships, workflows, and assets.
It verifies schema target validation, unsafe target rejection, required/select/
number/asset value validation, inaccessible asset rejection, backend-only
draft preparation, no ProviderJob/Version/Run/Node/Asset/Ledger side effects
during prepare, and EDITOR versus VIEWER project access. It does not mock
provider success or call external providers.

## Real provider command

```bash
SLOW_AI_REAL_PROVIDER_TESTS=1 WAVESPEED_API_KEY=xxx bench --site saas run-tests --app slow_ai
```

Run preflight coverage lives in:

```txt
slow_ai/tests/integration/test_run_preflight.py
```

It calls real `slow_ai.api.runs.start_run`, creates real `AI Model` and
`AI Provider Account` records, and verifies provider workflows are rejected
before enqueue when model, account, pricing, or budget policy fails. Rejected
preflight must not create `AI Workflow Version`, `AI Workflow Run`,
`AI Node Run`, or `AI Provider Job` records and must not call providers.

Project membership coverage lives in:

```txt
slow_ai/tests/integration/test_project_membership.py
```

It creates real users, projects, memberships, workflows, runs, assets, billing
ledger rows, provider accounts, and provider-node workflow drafts. It verifies
owner/System Manager membership administration, VIEWER read-only access,
EDITOR save/start access, BILLING billing/provider-account access, scoped run
library access, share creation rules, safe provider account payloads, and
insufficient-balance preflight rejection without workflow version/run/node or
provider-job side effects.
