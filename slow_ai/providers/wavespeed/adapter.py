"""WaveSpeed ProviderAdapter implementation."""

from __future__ import annotations

from typing import Any, Mapping

import frappe

from slow_ai.domain.exceptions import ProviderInvariantError
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.providers.contracts import (
    NormalizedProviderResult,
    ProviderAdapter,
    ProviderJobRequest,
    ProviderSubmission,
)
from slow_ai.providers.wavespeed.auth import WaveSpeedAuth
from slow_ai.providers.wavespeed.client import WaveSpeedClient
from slow_ai.providers.wavespeed.errors import WaveSpeedAuthError, WaveSpeedHTTPError
from slow_ai.providers.wavespeed.models import WAVESPEED_PROVIDER_NAME
from slow_ai.providers.wavespeed.normalizer import WaveSpeedNormalizer


class WaveSpeedAdapter(ProviderAdapter):
    provider_name = WAVESPEED_PROVIDER_NAME

    def __init__(
        self,
        *,
        client: WaveSpeedClient | None = None,
        auth: WaveSpeedAuth | None = None,
        normalizer: WaveSpeedNormalizer | None = None,
        provider_jobs: ProviderJobRepository | None = None,
    ) -> None:
        self.client = client or WaveSpeedClient()
        self.auth = auth or WaveSpeedAuth()
        self.normalizer = normalizer or WaveSpeedNormalizer()
        self.provider_jobs = provider_jobs or ProviderJobRepository()

    def create_and_submit_job(self, request: ProviderJobRequest) -> NormalizedProviderResult:
        self._ensure_wavespeed_request(request.provider)
        provider_job_name = self.provider_jobs.create_queued_job(request)
        return self.submit_job(
            ProviderSubmission(
                provider_job_name=provider_job_name,
                model=request.model,
                input_data=request.input_data,
            )
        )

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        provider_job = self.provider_jobs.get(submission.provider_job_name)
        self._ensure_wavespeed_request(provider_job.provider)

        if provider_job.external_job_id and provider_job.status in {
            ProviderJobStatus.SUBMITTED.value,
            ProviderJobStatus.WAITING_PROVIDER.value,
        }:
            return self.poll_job(provider_job.name)

        if provider_job.status == ProviderJobStatus.QUEUED.value:
            self.provider_jobs.mark_submitting(provider_job.name)
            provider_job = self.provider_jobs.get(provider_job.name)

        api_key = self._get_api_key_or_fail(provider_job)
        if api_key is None:
            return self._mark_auth_failure(provider_job.name)

        try:
            raw_response = self.client.submit_task(
                api_key,
                self._resolve_model_id(submission.model),
                submission.input_data,
            )
        except WaveSpeedHTTPError as exc:
            return self._apply_error(provider_job.name, exc.response_body)

        result = self.normalize_result(raw_response)
        self.provider_jobs.apply_result(provider_job.name, result, raw_response)
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        provider_job = self.provider_jobs.get(provider_job_name)
        self._ensure_wavespeed_request(provider_job.provider)
        if not provider_job.external_job_id:
            raise ProviderInvariantError("Cannot poll WaveSpeed job without external_job_id.")

        api_key = self._get_api_key_or_fail(provider_job)
        if api_key is None:
            return self._mark_auth_failure(provider_job.name)

        try:
            raw_response = self.client.get_result(api_key, provider_job.external_job_id)
        except WaveSpeedHTTPError as exc:
            return self._apply_error(provider_job.name, exc.response_body)

        result = self.normalize_result(raw_response)
        self.provider_jobs.apply_result(provider_job.name, result, raw_response)
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        provider_job = self.provider_jobs.get(provider_job_name)
        self._ensure_wavespeed_request(provider_job.provider)
        raw_response: Mapping[str, Any] | None = None
        if provider_job.external_job_id:
            api_key = self._get_api_key_or_fail(provider_job)
            if api_key is None:
                self._mark_auth_failure(provider_job.name)
                return
            try:
                raw_response = self.client.cancel_task(api_key, provider_job.external_job_id)
            except WaveSpeedHTTPError as exc:
                self._apply_error(provider_job.name, exc.response_body)
                return
        self.provider_jobs.mark_cancelled(provider_job.name, raw_response)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return self.normalizer.normalize(raw_response)

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.0, "model": model}

    def _mark_auth_failure(self, provider_job_name: str) -> NormalizedProviderResult:
        raw_response = {
            "code": 401,
            "message": "WaveSpeed API key is unavailable or invalid for this provider account.",
        }
        return self._apply_error(provider_job_name, raw_response)

    def _get_api_key_or_fail(self, provider_job) -> str | None:
        try:
            return self.auth.get_api_key(provider_job.provider_account)
        except WaveSpeedAuthError:
            return None

    def _apply_error(
        self,
        provider_job_name: str,
        raw_response: Mapping[str, Any] | str,
    ) -> NormalizedProviderResult:
        normalized_raw = raw_response if isinstance(raw_response, Mapping) else {"message": raw_response}
        result = self.normalize_result(normalized_raw)
        self.provider_jobs.apply_result(provider_job_name, result, normalized_raw)
        return result

    def _resolve_model_id(self, model: str) -> str:
        if frappe.db.exists("AI Model", model):
            return frappe.get_doc("AI Model", model).model_id
        return model

    def _ensure_wavespeed_request(self, provider: str) -> None:
        if provider != self.provider_name:
            raise ProviderInvariantError(f"WaveSpeed adapter cannot handle provider: {provider}")
