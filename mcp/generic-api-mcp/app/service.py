"""Application service layer for generic authenticated API access."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import AppConfig

QueryParamValue = str | int | float | bool | None


class GenericAPIService:
    """Fetch data from user-provided external API endpoints."""

    def __init__(self, config: AppConfig):
        self.config = config

    def fetch_generic_api_data(
        self,
        endpoint_url: str,
        query_params: dict[str, QueryParamValue] | None = None,
    ) -> dict[str, Any]:
        """Fetch data from the provided API endpoint."""
        endpoint = self._validate_endpoint_url(endpoint_url)
        params = self._normalize_query_params(query_params)
        try:
            response = requests.get(
                endpoint,
                auth=self.config.auth,
                params=params,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Generic API request failed: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            raise RuntimeError(
                f"Generic API request failed with HTTP {response.status_code}."
            )

        return {
            "ok": True,
            "status_code": response.status_code,
            "content_type": content_type,
            "data": self._response_data(response, content_type),
        }

    @staticmethod
    def _validate_endpoint_url(endpoint_url: str) -> str:
        if not isinstance(endpoint_url, str) or endpoint_url.strip() == "":
            raise ValueError("endpoint_url is required and must be a non-empty string.")
        endpoint = endpoint_url.strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint_url must be a valid http:// or https:// URL.")
        return endpoint

    @staticmethod
    def _normalize_query_params(
        query_params: dict[str, QueryParamValue] | None,
    ) -> dict[str, QueryParamValue] | None:
        if query_params is None:
            return None
        if not isinstance(query_params, dict):
            raise ValueError("query_params must be an object when provided.")
        normalized: dict[str, QueryParamValue] = {}
        for key, value in query_params.items():
            if not isinstance(key, str) or key.strip() == "":
                raise ValueError("query_params keys must be non-empty strings.")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    "query_params values must be strings, numbers, booleans, or null."
                )
            normalized[key] = value
        return normalized

    @staticmethod
    def _response_data(response: requests.Response, content_type: str) -> Any:
        if "json" not in content_type.lower():
            return response.text
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Generic API response declared JSON but was not valid JSON.") from exc


@lru_cache(maxsize=1)
def get_service() -> GenericAPIService:
    """Return the process-wide generic API service instance."""
    return GenericAPIService(AppConfig.from_env())
