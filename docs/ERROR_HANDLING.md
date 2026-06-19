# Error Handling

## Error shape

```json
{
  "error_type": "PROVIDER_TIMEOUT",
  "message": "Provider job timed out",
  "node_id": "video_1",
  "node_type": "provider_image_to_video",
  "provider_job": "AI-PROVIDER-JOB-0001",
  "retryable": true,
  "safe_details": {}
}
```

## Where to store errors

```txt
AI Workflow Run.error_json
AI Node Run.error_json
AI Provider Job.raw_error_json
```

## Error categories

```txt
VALIDATION_ERROR
UNKNOWN_NODE_TYPE
GRAPH_CYCLE
MISSING_INPUT
PROVIDER_SUBMIT_FAILED
PROVIDER_TIMEOUT
PROVIDER_FAILED
ASSET_WRITE_FAILED
CREDIT_LEDGER_FAILED
PERMISSION_DENIED
WORKER_CRASH
```
