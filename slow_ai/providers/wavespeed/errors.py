"""WaveSpeed provider errors."""

from __future__ import annotations

from typing import Any, Mapping


class WaveSpeedError(RuntimeError):
    """Base WaveSpeed adapter error."""


class WaveSpeedAuthError(WaveSpeedError):
    """Raised when a usable WaveSpeed API key cannot be found."""


class WaveSpeedHTTPError(WaveSpeedError):
    def __init__(self, status_code: int, response_body: Mapping[str, Any] | str) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"WaveSpeed API request failed with HTTP {status_code}.")
