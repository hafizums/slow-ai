# Tool Run Sharing Contract

## Purpose

Tool Run Sharing lets a logged-in user create a read-only link for selected
completed Tool Run outputs. The link is for viewing generated or selected
outputs only. It is not a public execution endpoint and must never allow
anonymous paid runs.

## Persistence

Shares are stored in `AI Tool Run Share`:

```txt
workflow_run
project
share_token
status: ACTIVE / DISABLED
selected_assets_json
expires_at
owner
creation / modified
```

The DocType controller is persistence-only. Permission checks, token generation,
expiry checks, and safe payload construction live in the application layer.

## APIs

```txt
slow_ai.api.public_tools.create_run_share
slow_ai.api.public_tools.disable_run_share
slow_ai.api.public_tools.get_shared_run
```

`create_run_share` requires a logged-in user with access to the run project. It
requires a non-empty `selected_assets` list and validates every selected AI
Asset against the workflow run before writing `selected_assets_json`. There is
no implicit share-all behavior. `disable_run_share` requires the share owner or
System Manager. `get_shared_run` allows guest access only for ACTIVE,
non-expired tokens.

## Shared Payload

Allowed:

```txt
safe run id/title/status/timestamps
selected safe output asset names and metadata
safe asset file/url values materialized by AI Asset view data
aggregate cost summary
share status/expiry timestamps
```

Forbidden:

```txt
provider account names
provider secrets
raw provider request_json
raw provider response_json
raw provider error JSON
provider adapter internals
workflow draft internals
project metadata
Run button or start_run calls
ProviderJob creation
Asset or ledger creation
anonymous paid runs
```

## Shared Page

`/slow-ai/shared/<token>` is read-only. It calls only
`slow_ai.api.public_tools.get_shared_run`, renders safe metadata and output
assets selected at share creation, and never calls provider APIs or
workflow/run creation APIs. Unselected run outputs must not be visible to
guests.

Shared payloads may internally reuse the Run Output Gallery service described
in `RUN_OUTPUT_GALLERY_CONTRACT.md`, but only with the selected assets stored
on the share record, with unselected outputs excluded, and with nested gallery
run metadata reduced to the same public run id/title/status/timestamp fields.
