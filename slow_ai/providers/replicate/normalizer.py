"""Normalize Replicate responses into provider-neutral results."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlparse

from slow_ai.domain.status import ProviderJobStatus
from slow_ai.providers.contracts import NormalizedProviderOutput, NormalizedProviderResult


class ReplicateNormalizer:
    def normalize(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        if _is_error_response(raw_response):
            return NormalizedProviderResult(
                status=ProviderJobStatus.FAILED.value,
                external_job_id=_external_job_id(raw_response),
                error=_error_payload(raw_response),
            )

        status = _normalize_status(str(raw_response.get("status") or "").lower())
        outputs = tuple(_normalize_output(output) for output in _outputs(raw_response))
        error = _error_payload(raw_response) if status == ProviderJobStatus.FAILED else None
        return NormalizedProviderResult(
            status=status.value,
            external_job_id=_external_job_id(raw_response),
            outputs=outputs,
            cost_usd=_cost_usd(raw_response),
            error=error,
        )


def _is_error_response(raw_response: Mapping[str, Any]) -> bool:
    code = raw_response.get("code") or raw_response.get("status_code")
    try:
        return code is not None and int(code) >= 400
    except (TypeError, ValueError):
        return False


def _normalize_status(raw_status: str) -> ProviderJobStatus:
    if raw_status in {"starting"}:
        return ProviderJobStatus.SUBMITTED
    if raw_status in {"processing"}:
        return ProviderJobStatus.WAITING_PROVIDER
    if raw_status in {"succeeded", "success", "completed"}:
        return ProviderJobStatus.SUCCEEDED
    if raw_status in {"failed", "error"}:
        return ProviderJobStatus.FAILED
    if raw_status in {"canceled", "cancelled"}:
        return ProviderJobStatus.CANCELLED
    return ProviderJobStatus.WAITING_PROVIDER


def _outputs(raw_response: Mapping[str, Any]) -> tuple[Any, ...]:
    raw_outputs = raw_response.get("output") or raw_response.get("outputs") or ()
    if isinstance(raw_outputs, (str, Mapping)):
        return (raw_outputs,)
    return tuple(raw_outputs)


def _normalize_output(output: Any) -> NormalizedProviderOutput:
    if isinstance(output, str):
        url = output
        mime_type = _guess_mime_type(url)
        return NormalizedProviderOutput(
            asset_type=_guess_asset_type(mime_type),
            url=url,
            mime_type=mime_type,
            metadata={},
        )

    output_map = _as_mapping(output)
    url = str(output_map.get("url") or output_map.get("uri") or output_map.get("href") or "")
    mime_type = str(output_map.get("mime_type") or output_map.get("mimeType") or _guess_mime_type(url))
    return NormalizedProviderOutput(
        asset_type=str(output_map.get("asset_type") or output_map.get("type") or _guess_asset_type(mime_type)).upper(),
        url=url,
        mime_type=mime_type,
        metadata={key: value for key, value in output_map.items() if key not in {"url", "uri", "href"}},
    )


def _guess_mime_type(url: str) -> str:
    if url.startswith("data:") and ";" in url:
        return url[5 : url.index(";")]
    extension = PurePosixPath(urlparse(url).path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".json": "application/json",
        ".txt": "text/plain",
    }.get(extension, "application/json")


def _guess_asset_type(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "IMAGE"
    if mime_type.startswith("video/"):
        return "VIDEO"
    if mime_type.startswith("audio/"):
        return "AUDIO"
    if mime_type == "text/plain":
        return "TEXT"
    return "JSON"


def _error_payload(raw_response: Mapping[str, Any]) -> Mapping[str, Any]:
    error = raw_response.get("error") or raw_response.get("detail") or raw_response.get("message")
    if isinstance(error, Mapping):
        return error
    return {"message": str(error or "Replicate provider request failed.")}


def _external_job_id(raw_response: Mapping[str, Any]) -> str | None:
    external_job_id = raw_response.get("id") or raw_response.get("prediction_id")
    if external_job_id is None:
        return None
    return str(external_job_id)


def _cost_usd(raw_response: Mapping[str, Any]) -> float:
    metrics = _as_mapping(raw_response.get("metrics"))
    for value in (raw_response.get("cost_usd"), raw_response.get("cost"), metrics.get("cost_usd")):
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}
