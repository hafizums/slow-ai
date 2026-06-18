"""WaveSpeed REST client."""

from __future__ import annotations

from typing import Any, Mapping

import requests

from slow_ai.providers.wavespeed.errors import WaveSpeedHTTPError
from slow_ai.providers.wavespeed.models import WAVESPEED_BASE_URL


class WaveSpeedClient:
    def __init__(self, base_url: str = WAVESPEED_BASE_URL, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def submit_task(
        self,
        api_key: str,
        model: str,
        input_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._request(
            "POST",
            f"/{model.lstrip('/')}",
            api_key=api_key,
            json_body=dict(input_data),
        )

    def get_result(self, api_key: str, external_job_id: str) -> Mapping[str, Any]:
        return self._request("GET", f"/predictions/{external_job_id}/result", api_key=api_key)

    def cancel_task(self, api_key: str, external_job_id: str) -> Mapping[str, Any]:
        return self._request("DELETE", f"/predictions/{external_job_id}", api_key=api_key)

    def _request(
        self,
        method: str,
        path: str,
        *,
        api_key: str,
        json_body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=json_body,
            timeout=self.timeout_seconds,
        )
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text
        if response.status_code >= 400:
            raise WaveSpeedHTTPError(response.status_code, response_body)
        return response_body
