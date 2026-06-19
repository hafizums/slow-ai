"""Replicate provider errors."""

from __future__ import annotations

from typing import Any


class ReplicateError(Exception):
    """Base error for Replicate provider integration."""


class ReplicateAuthError(ReplicateError):
    """Raised when no usable Replicate credential is available."""


class ReplicateHTTPError(ReplicateError):
    """Raised when Replicate returns an error HTTP response."""

    def __init__(self, status_code: int, response_body: Any) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Replicate request failed with HTTP {status_code}.")
