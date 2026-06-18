import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.status import ProviderJobStatus
from slow_ai.providers.contracts import ProviderJobRequest
from slow_ai.providers.registry import create_default_provider_registry
from slow_ai.providers.wavespeed.adapter import WaveSpeedAdapter
from slow_ai.providers.wavespeed.auth import WaveSpeedAuth
from slow_ai.providers.wavespeed.normalizer import WaveSpeedNormalizer


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class RecordingWaveSpeedClient:
    def __init__(self, *, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        self.submitted: list[Mapping[str, Any]] = []
        self.polled: list[str] = []

    def submit_task(
        self,
        api_key: str,
        model: str,
        input_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        existing = frappe.get_all(
            "AI Provider Job",
            filters={
                "idempotency_key": self.idempotency_key,
                "status": ProviderJobStatus.SUBMITTING.value,
            },
            fields=["name"],
            limit=1,
        )
        assert existing, "AI Provider Job must exist before external WaveSpeed submission."
        self.submitted.append({"api_key": api_key, "model": model, "input_data": dict(input_data)})
        return {
            "code": 200,
            "message": "success",
            "data": {
                "id": "pred_submit_123",
                "model": model,
                "status": "created",
                "urls": {"get": "https://api.wavespeed.ai/api/v3/predictions/pred_submit_123"},
            },
        }

    def get_result(self, api_key: str, external_job_id: str) -> Mapping[str, Any]:
        self.polled.append(external_job_id)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "id": external_job_id,
                "status": "completed",
                "outputs": ["https://example.invalid/generated.png"],
            },
        }

    def cancel_task(self, api_key: str, external_job_id: str) -> Mapping[str, Any]:
        return {"code": 200, "data": {"id": external_job_id, "status": "cancelled"}}


class FailedWaveSpeedClient(RecordingWaveSpeedClient):
    def get_result(self, api_key: str, external_job_id: str) -> Mapping[str, Any]:
        self.polled.append(external_job_id)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "id": external_job_id,
                "status": "failed",
                "error": {"message": "Generation failed."},
            },
        }


class TestWaveSpeedProvider(FrappeTestCase):
    def create_provider_catalog(self) -> tuple[str, str]:
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("wavespeed-ai/flux-dev"),
                "model_name": "WaveSpeed Flux Dev",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.0}),
            }
        )
        provider_account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": "wavespeed",
                "account_label": unique("WaveSpeed Test"),
                "api_key_secret": "test-wavespeed-secret",
                "is_default": 1,
                "status": "ACTIVE",
                "rate_limit_json": json.dumps({"rpm": 60}),
            }
        )
        return model.name, provider_account.name

    def test_default_provider_registry_includes_wavespeed(self):
        registry = create_default_provider_registry()

        self.assertTrue(registry.has("wavespeed"))
        self.assertIsInstance(registry.get("wavespeed"), WaveSpeedAdapter)

    def test_wavespeed_auth_reads_server_side_provider_account_secret(self):
        _, provider_account_name = self.create_provider_catalog()

        self.assertEqual(
            WaveSpeedAuth().get_api_key(provider_account_name),
            "test-wavespeed-secret",
        )

    def test_create_and_submit_job_persists_provider_job_before_external_submit(self):
        model_name, provider_account_name = self.create_provider_catalog()
        idempotency_key = unique("ws-submit")
        client = RecordingWaveSpeedClient(idempotency_key=idempotency_key)
        adapter = WaveSpeedAdapter(client=client)

        result = adapter.create_and_submit_job(
            ProviderJobRequest(
                provider="wavespeed",
                model=model_name,
                provider_account_name=provider_account_name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot", "size": "1024*1024"},
            )
        )

        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.SUBMITTED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUBMITTED.value)
        self.assertEqual(provider_job.external_job_id, "pred_submit_123")
        self.assertEqual(json.loads(provider_job.request_json)["prompt"], "A product shot")
        self.assertEqual(client.submitted[0]["api_key"], "test-wavespeed-secret")
        self.assertEqual(client.submitted[0]["model"], model_name)
        self.assertTrue(provider_job.submitted_at)

    def test_poll_job_persists_completed_result_and_normalized_outputs(self):
        model_name, provider_account_name = self.create_provider_catalog()
        idempotency_key = unique("ws-poll")
        client = RecordingWaveSpeedClient(idempotency_key=idempotency_key)
        adapter = WaveSpeedAdapter(client=client)
        adapter.create_and_submit_job(
            ProviderJobRequest(
                provider="wavespeed",
                model=model_name,
                provider_account_name=provider_account_name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot"},
            )
        )
        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )

        result = adapter.poll_job(provider_job_name)

        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(result.outputs[0].asset_type, "IMAGE")
        self.assertEqual(result.outputs[0].mime_type, "image/png")
        self.assertTrue(provider_job.completed_at)

    def test_poll_job_persists_failed_result_error_payload(self):
        model_name, provider_account_name = self.create_provider_catalog()
        idempotency_key = unique("ws-failed")
        client = FailedWaveSpeedClient(idempotency_key=idempotency_key)
        adapter = WaveSpeedAdapter(client=client)
        adapter.create_and_submit_job(
            ProviderJobRequest(
                provider="wavespeed",
                model=model_name,
                provider_account_name=provider_account_name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot"},
            )
        )
        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )

        result = adapter.poll_job(provider_job_name)

        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(json.loads(provider_job.raw_error_json)["message"], "Generation failed.")
        self.assertTrue(provider_job.completed_at)

    def test_wavespeed_normalizer_maps_video_outputs(self):
        result = WaveSpeedNormalizer().normalize(
            {
                "code": 200,
                "data": {
                    "id": "pred_video_123",
                    "status": "completed",
                    "outputs": ["https://example.invalid/generated.mp4"],
                },
            }
        )

        self.assertEqual(result.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(result.outputs[0].asset_type, "VIDEO")
        self.assertEqual(result.outputs[0].mime_type, "video/mp4")
