from __future__ import annotations

# ruff: noqa: E402,I001

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_ROOT))

from app.config import AppConfig
from app.service import GenericAPIService


def test_fastmcp_server_builds_when_sdk_is_installed():
    pytest.importorskip("mcp.server.fastmcp")

    from app.mcp_server import build_mcp

    server = build_mcp()

    assert server.name == "generic_api_mcp"


def test_config_starts_without_endpoint_or_credentials(monkeypatch):
    monkeypatch.delenv("GENERIC_API_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("GENERIC_API_USERNAME", raising=False)
    monkeypatch.delenv("GENERIC_API_PASSWORD", raising=False)

    config = AppConfig.from_env()

    assert config.timeout_seconds == 30.0
    assert config.auth is None


def test_config_uses_basic_auth_only_when_both_credentials_exist(monkeypatch):
    monkeypatch.setenv("GENERIC_API_USERNAME", "user")
    monkeypatch.delenv("GENERIC_API_PASSWORD", raising=False)
    assert AppConfig.from_env().auth is None

    monkeypatch.delenv("GENERIC_API_USERNAME", raising=False)
    monkeypatch.setenv("GENERIC_API_PASSWORD", "secret")
    assert AppConfig.from_env().auth is None

    monkeypatch.setenv("GENERIC_API_USERNAME", "user")
    monkeypatch.setenv("GENERIC_API_PASSWORD", "secret")
    assert AppConfig.from_env().auth == ("user", "secret")


def test_config_reads_timeout(monkeypatch):
    monkeypatch.setenv("GENERIC_API_USERNAME", "user")
    monkeypatch.setenv("GENERIC_API_PASSWORD", "secret")
    monkeypatch.setenv("GENERIC_API_TIMEOUT_SECONDS", "12.5")

    config = AppConfig.from_env()

    assert config.timeout_seconds == 12.5
    assert "secret" not in repr(config)


def test_config_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("GENERIC_API_TIMEOUT_SECONDS", "nope")

    with pytest.raises(ValueError, match="GENERIC_API_TIMEOUT_SECONDS must be a number"):
        AppConfig.from_env()


def test_fetch_passes_endpoint_and_query_params_without_auth(monkeypatch):
    captured = {}

    def fake_get(url, auth, params, timeout, allow_redirects=True):
        captured.update({"url": url, "auth": auth, "params": params, "timeout": timeout})
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {"items": [1]},
            text='{"items":[1]}',
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(AppConfig(timeout_seconds=7))

    result = service.fetch_generic_api_data(
        endpoint_url="https://api.example.test/data",
        query_params={"limit": 3, "active": True},
    )

    assert captured == {
        "url": "https://api.example.test/data",
        "auth": None,
        "params": {"limit": 3, "active": True},
        "timeout": 7,
    }
    assert result == {
        "ok": True,
        "status_code": 200,
        "content_type": "application/json",
        "data": {"items": [1]},
    }


def test_fetch_passes_basic_auth_when_optional_credentials_exist(monkeypatch):
    captured = {}

    def fake_get(url, auth, params, timeout, allow_redirects=True):
        captured.update({"auth": auth})
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {"ok": True},
            text='{"ok":true}',
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(
        AppConfig(
            username="user",
            password="secret",
            allowed_hosts=frozenset({"api.example.test"}),
        )
    )

    service.fetch_generic_api_data(endpoint_url="https://API.example.test/data")

    assert captured["auth"] == ("user", "secret")


def test_credentials_are_not_sent_to_hosts_outside_the_allowlist(monkeypatch):
    # The endpoint is chosen by the model: without the allowlist a prompt
    # injection could have the credentials sent to any server it names.
    captured = []

    def fake_get(url, auth, params, timeout, allow_redirects=True):
        captured.append((url, auth, allow_redirects))
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/plain"},
            text="ok",
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    for config in (
        AppConfig(username="user", password="secret"),
        AppConfig(
            username="user",
            password="secret",
            allowed_hosts=frozenset({"api.example.test"}),
        ),
    ):
        GenericAPIService(config).fetch_generic_api_data(
            endpoint_url="https://attacker.example.test/collect"
        )

    assert [auth for _url, auth, _redirects in captured] == [None, None]
    # Redirects are never delegated to requests.
    assert all(redirects is False for _url, _auth, redirects in captured)


def test_allowed_hosts_are_read_from_env(monkeypatch):
    monkeypatch.setenv("GENERIC_API_ALLOWED_HOSTS", " API.Example.test , other.example.test ,")
    config = AppConfig.from_env()
    assert config.allowed_hosts == frozenset({"api.example.test", "other.example.test"})
    monkeypatch.delenv("GENERIC_API_ALLOWED_HOSTS")
    assert AppConfig.from_env().allowed_hosts == frozenset()


def test_internal_endpoints_are_refused_before_any_request(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("network reached for an internal endpoint")

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(AppConfig())
    for endpoint in (
        "http://localhost:8080/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://metadata.google.internal/",
        "http://[::1]/",
        "http://2130706433/",
    ):
        with pytest.raises(ValueError, match="not allowed"):
            service.fetch_generic_api_data(endpoint_url=endpoint)


def test_redirects_are_reported_not_followed(monkeypatch):
    def fake_get(url, auth, params, timeout, allow_redirects=True):
        return SimpleNamespace(
            status_code=302,
            headers={"location": "http://127.0.0.1/admin"},
            text="",
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(AppConfig())
    with pytest.raises(RuntimeError, match="redirect"):
        service.fetch_generic_api_data(endpoint_url="https://api.example.test/data")


def test_fetch_returns_text_response(monkeypatch):
    def fake_get(url, auth, params, timeout, allow_redirects=True):
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/plain"},
            text="hello",
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(AppConfig())

    result = service.fetch_generic_api_data(endpoint_url="https://api.example.test/data")

    assert result["content_type"] == "text/plain"
    assert result["data"] == "hello"


def test_fetch_http_error_is_clear(monkeypatch):
    def fake_get(url, auth, params, timeout, allow_redirects=True):
        return SimpleNamespace(
            status_code=404,
            headers={"content-type": "application/json"},
            text='{"error":"not found"}',
        )

    monkeypatch.setattr("app.service.requests.get", fake_get)
    service = GenericAPIService(AppConfig())

    with pytest.raises(RuntimeError, match="HTTP 404"):
        service.fetch_generic_api_data(endpoint_url="https://api.example.test/data")


def test_fetch_request_exception_is_clear(monkeypatch):
    def fake_get(url, auth, params, timeout, allow_redirects=True):
        import app.service as service_module

        raise service_module.requests.RequestException("network down")

    monkeypatch.setattr("app.service.requests.get", fake_get)

    service = GenericAPIService(AppConfig())

    with pytest.raises(RuntimeError, match="network down"):
        service.fetch_generic_api_data(endpoint_url="https://api.example.test/data")


def test_endpoint_url_validation_rejects_missing_or_invalid_values():
    service = GenericAPIService(AppConfig())

    with pytest.raises(ValueError, match="endpoint_url is required"):
        service.fetch_generic_api_data(endpoint_url="")
    with pytest.raises(ValueError, match="http:// or https://"):
        service.fetch_generic_api_data(endpoint_url="ftp://api.example.test/data")
    with pytest.raises(ValueError, match="http:// or https://"):
        service.fetch_generic_api_data(endpoint_url="https://")


def test_query_params_validation_rejects_invalid_values():
    service = GenericAPIService(AppConfig())

    with pytest.raises(ValueError, match="keys must be non-empty strings"):
        service.fetch_generic_api_data(
            endpoint_url="https://api.example.test/data",
            query_params={"": "bad"},
        )
    with pytest.raises(ValueError, match="values must be strings"):
        service.fetch_generic_api_data(
            endpoint_url="https://api.example.test/data",
            query_params={"bad": []},  # type: ignore[dict-item]
        )
