"""Replicate REST client."""

from __future__ import annotations

from typing import Any, Mapping

import requests

from slow_ai.providers.replicate.errors import ReplicateHTTPError
from slow_ai.providers.replicate.models import REPLICATE_BASE_URL


class ReplicateClient:
    def __init__(self, base_url: str = REPLICATE_BASE_URL, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def create_prediction(
        self,
        api_key: str,
        version: str,
        input_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/predictions",
            api_key=api_key,
            json_body={"version": version, "input": dict(input_data)},
        )

    def get_prediction(self, api_key: str, prediction_id: str) -> Mapping[str, Any]:
        return self._request("GET", f"/predictions/{prediction_id}", api_key=api_key)

    def cancel_prediction(self, api_key: str, prediction_id: str) -> Mapping[str, Any]:
        return self._request("POST", f"/predictions/{prediction_id}/cancel", api_key=api_key)

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
            raise ReplicateHTTPError(response.status_code, response_body)
        return response_body
