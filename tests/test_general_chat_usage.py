"""Tests for usage metering, pricing, and quotas."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.pricing import (  # noqa: E402
    PricingCache,
    default_pricing,
    invalid_pricing_values,
)
from general_chat.quotas import (  # noqa: E402
    QuotaCache,
    invalid_quota_values,
    quota_status,
    resolve_quotas,
)
from general_chat.usage_metering import UsageRecorder, _MeteringLLMProvider  # noqa: E402
from general_chat.usage_store import (  # noqa: E402
    JsonUsageStore,
    PostgresUsageStore,
    UsageRecord,
    current_month,
)

from openbench.core.abstractions import LLMResponse  # noqa: E402

pytestmark = pytest.mark.integration


class _MemorySettings:
    def __init__(self):
        self.data: dict = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, *, updated_by=""):
        self.data[key] = value


class _FakeProvider:
    """Minimal inner provider for wrapper tests."""

    provider_name = "fake"

    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    def generate(self, prompt, model="", **params):
        self.calls += 1
        return self._responses[0]

    def generate_stream(self, prompt, model="", **params):
        self.calls += 1
        yield from self._responses


def _response(text="", tokens=0, prompt_tokens=0, completion_tokens=0):
    metadata = {}
    if prompt_tokens or completion_tokens:
        metadata = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return LLMResponse(
        text=text, model="gemini-3.5-flash", tokens_used=tokens, cost=0.0, metadata=metadata
    )


class TestMeteringProvider(unittest.TestCase):
    def _wrapper(self, responses):
        captured: list[tuple[str, int, int]] = []
        inner = _FakeProvider(responses)
        wrapper = _MeteringLLMProvider(
            inner, lambda model, pt, ct: captured.append((model, pt, ct))
        )
        return wrapper, captured

    def test_generate_records_usage(self):
        wrapper, captured = self._wrapper(
            [_response(text="halo", tokens=30, prompt_tokens=10, completion_tokens=20)]
        )
        response = wrapper.generate("hi", model="gemini-3.5-flash")
        self.assertEqual(response.text, "halo")
        self.assertEqual(captured, [("gemini-3.5-flash", 10, 20)])

    def test_stream_records_only_usage_bearing_chunks(self):
        wrapper, captured = self._wrapper(
            [
                _response(text="Halo "),
                _response(text="dunia"),
                _response(tokens=10, prompt_tokens=7, completion_tokens=3),
            ]
        )
        chunks = list(wrapper.generate_stream("hi", model="gemini-3.5-flash"))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(captured, [("gemini-3.5-flash", 7, 3)])

    def test_callback_failure_does_not_break_stream(self):
        inner = _FakeProvider([_response(tokens=5, prompt_tokens=3, completion_tokens=2)])

        def boom(model, pt, ct):
            raise RuntimeError("metering down")

        wrapper = _MeteringLLMProvider(inner, boom)
        chunks = list(wrapper.generate_stream("hi", model="m"))
        self.assertEqual(len(chunks), 1)

    def test_delegates_unknown_attributes(self):
        inner = _FakeProvider([])
        inner.custom_attr = "x"
        wrapper = _MeteringLLMProvider(inner, lambda *a: None)
        self.assertEqual(wrapper.custom_attr, "x")
        self.assertEqual(wrapper.provider_name, "fake")


class TestUsageRecorder(unittest.TestCase):
    def test_cost_uses_current_admin_rates(self):
        settings = _MemorySettings()
        pricing = PricingCache(settings)
        pricing.update(
            {"models": {"gemini-3.5-flash": {"input_per_1m": 2.0, "output_per_1m": 4.0}}}
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = JsonUsageStore(tmp.name)
        recorder = UsageRecorder(store, pricing)

        recorder.record(
            owner="a@x.co",
            session_id="s1",
            model="gemini-3.5-flash",
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
        )
        row = store.recent("a@x.co")[0]
        self.assertAlmostEqual(row.cost_usd, 2.0 + 2.0)
        self.assertEqual(row.total_tokens, 1_500_000)
        self.assertEqual(row.session_id, "s1")

    def test_store_failure_swallowed(self):
        store = Mock()
        store.append.side_effect = RuntimeError("disk full")
        recorder = UsageRecorder(store, PricingCache(_MemorySettings()))
        recorder.record(
            owner="a@x.co", session_id="", model="m", prompt_tokens=1, completion_tokens=1
        )  # must not raise


class TestJsonUsageStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonUsageStore(tmp.name)

    def test_summaries_filter_by_month_and_owner(self):
        self.store.append(
            UsageRecord(
                owner="a@x.co", prompt_tokens=10, completion_tokens=5, total_tokens=15,
                cost_usd=0.1, ts="2026-08-01T10:00:00+00:00",
            )
        )
        self.store.append(
            UsageRecord(
                owner="a@x.co", prompt_tokens=1, completion_tokens=1, total_tokens=2,
                cost_usd=0.01, ts="2026-07-30T10:00:00+00:00",
            )
        )
        self.store.append(
            UsageRecord(
                owner="b@x.co", prompt_tokens=100, completion_tokens=50, total_tokens=150,
                cost_usd=1.0, ts="2026-08-02T10:00:00+00:00",
            )
        )
        summary = self.store.summarize_owner("a@x.co", "2026-08")
        self.assertEqual(summary["totalTokens"], 15)
        self.assertEqual(summary["calls"], 1)

        everyone = self.store.summarize_all("2026-08")
        self.assertEqual([entry["owner"] for entry in everyone], ["a@x.co", "b@x.co"])
        self.assertEqual(everyone[1]["costUsd"], 1.0)

    def test_recent_orders_newest_first(self):
        for hour in (1, 3, 2):
            self.store.append(
                UsageRecord(owner="a@x.co", ts=f"2026-08-01T{hour:02d}:00:00+00:00")
            )
        rows = self.store.recent("a@x.co", limit=2)
        self.assertEqual([r.ts[11:13] for r in rows], ["03", "02"])


class TestPostgresUsageStoreStructure(unittest.TestCase):
    def test_interface_and_sql_shape(self):
        executed: list[str] = []

        class _Cursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Conn:
            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

        PostgresUsageStore(conn=_Conn())
        joined = "\n".join(executed)
        self.assertIn("openbench_usage", joined)
        for column in ("owner", "session_id", "model", "prompt_tokens", "cost_usd"):
            self.assertIn(column, joined)
        for method in ("append", "summarize_owner", "summarize_all", "recent"):
            self.assertTrue(callable(getattr(PostgresUsageStore, method, None)))


class TestPricing(unittest.TestCase):
    def test_seed_matches_sdk_costs(self):
        from openbench.intelligence.llm_providers.costs import _GEMINI_COSTS

        models = default_pricing()["models"]
        for model, rates in _GEMINI_COSTS.items():
            self.assertEqual(models[model]["input_per_1m"], rates["input"])
            self.assertEqual(models[model]["output_per_1m"], rates["output"])

    def test_update_changes_compute_cost(self):
        cache = PricingCache(_MemorySettings())
        baseline = cache.compute_cost("gemini-2.5-flash", 1_000_000, 0)
        self.assertAlmostEqual(baseline, 0.15)
        cache.update({"models": {"gemini-2.5-flash": {"input_per_1m": 1.5}}})
        self.assertAlmostEqual(cache.compute_cost("gemini-2.5-flash", 1_000_000, 0), 1.5)
        # Output rate untouched by the partial update.
        self.assertAlmostEqual(cache.compute_cost("gemini-2.5-flash", 0, 1_000_000), 0.60)

    def test_unknown_model_costs_zero(self):
        cache = PricingCache(_MemorySettings())
        self.assertEqual(cache.compute_cost("mystery-model", 1000, 1000), 0.0)

    def test_invalid_values(self):
        self.assertIn(
            "gemini-2.5-flash.input_per_1m",
            invalid_pricing_values({"models": {"gemini-2.5-flash": {"input_per_1m": -1}}}),
        )
        self.assertIn("models", invalid_pricing_values({"models": "x"}))
        self.assertEqual(invalid_pricing_values({}), {})


class TestQuotas(unittest.TestCase):
    def test_resolution_and_override(self):
        cache = QuotaCache(_MemorySettings())
        self.assertEqual(cache.quota_for("a@x.co"), 0)
        cache.update({"default_monthly_tokens": 1000, "overrides": {"A@X.co": 50}})
        self.assertEqual(cache.quota_for("b@x.co"), 1000)
        self.assertEqual(cache.quota_for("a@x.co"), 50)

    def test_resolve_drops_bad_entries(self):
        resolved = resolve_quotas(
            {"default_monthly_tokens": -5, "overrides": {"a@x.co": "x", "b@x.co": 10}}
        )
        self.assertEqual(resolved["default_monthly_tokens"], 0)
        self.assertEqual(resolved["overrides"], {"b@x.co": 10})

    def test_invalid_values(self):
        self.assertIn(
            "default_monthly_tokens", invalid_quota_values({"default_monthly_tokens": True})
        )
        self.assertIn("overrides.a", invalid_quota_values({"overrides": {"a": -1}}))
        self.assertEqual(invalid_quota_values({"default_monthly_tokens": 10}), {})

    def test_quota_status_warn_only_math(self):
        self.assertEqual(
            quota_status(0, 999), {"limit": 0, "used": 999, "warning": False, "percent": 0.0}
        )
        self.assertEqual(
            quota_status(100, 50),
            {"limit": 100, "used": 50, "warning": False, "percent": 50.0},
        )
        status = quota_status(100, 150)
        self.assertTrue(status["warning"])
        self.assertEqual(status["percent"], 100.0)


class TestUsageEndpoints(unittest.TestCase):
    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.storage_root = Path(tmp.name) / "storage"
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.storage_root),
                    "GENERAL_CHAT_UPLOAD_DIR": str(Path(tmp.name) / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(Path(tmp.name) / "downloads"),
                    "GENERAL_CHAT_MEMORY_DB": str(Path(tmp.name) / "memory.db"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(Path(tmp.name) / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _seed_rows(self):
        store = JsonUsageStore(self.storage_root)
        month = current_month()
        store.append(
            UsageRecord(
                owner="local", model="gemini-3.5-flash", prompt_tokens=100,
                completion_tokens=50, total_tokens=150, cost_usd=0.5,
                ts=f"{month}-01T10:00:00+00:00",
            )
        )
        store.append(
            UsageRecord(
                owner="user@corp.co.id", prompt_tokens=10, completion_tokens=5,
                total_tokens=15, cost_usd=0.1, ts=f"{month}-02T10:00:00+00:00",
            )
        )

    def test_account_usage_scoped_to_requester(self):
        client = self._client()
        self._seed_rows()
        payload = client.get("/account/usage").json()
        self.assertEqual(payload["totalTokens"], 150)
        self.assertEqual(payload["costUsd"], 0.5)
        self.assertEqual(payload["quota"]["limit"], 0)
        self.assertFalse(payload["quota"]["warning"])
        self.assertEqual(len(payload["recent"]), 1)
        self.assertEqual(payload["recent"][0]["model"], "gemini-3.5-flash")

    def test_account_usage_available_to_plain_users(self):
        client = self._client()
        response = client.get("/account/usage", headers={"X-Local-Role": "user"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["totalTokens"], 0)

    def test_account_usage_quota_warning(self):
        client = self._client()
        self._seed_rows()
        client.put("/admin/quotas", json={"overrides": {"local": 100}})
        payload = client.get("/account/usage").json()
        self.assertEqual(payload["quota"]["limit"], 100)
        self.assertTrue(payload["quota"]["warning"])

    def test_admin_usage_aggregates_all_owners(self):
        client = self._client()
        self._seed_rows()
        payload = client.get("/admin/usage").json()
        self.assertEqual(payload["totals"]["totalTokens"], 165)
        self.assertEqual(
            [user["owner"] for user in payload["users"]], ["local", "user@corp.co.id"]
        )

    def test_admin_endpoints_forbidden_for_users(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        for path in ("/admin/usage", "/admin/pricing", "/admin/quotas"):
            self.assertEqual(client.get(path, headers=headers).status_code, 403, path)

    def test_pricing_roundtrip_and_validation(self):
        client = self._client()
        payload = client.get("/admin/pricing").json()
        self.assertIn("gemini-3.5-flash", payload["models"])
        response = client.put(
            "/admin/pricing",
            json={"models": {"gemini-3.5-flash": {"input_per_1m": 0.5}}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"]["gemini-3.5-flash"]["input_per_1m"], 0.5)
        bad = client.put(
            "/admin/pricing", json={"models": {"gemini-3.5-flash": {"input_per_1m": -1}}}
        )
        self.assertEqual(bad.status_code, 400)

    def test_quotas_roundtrip_and_validation(self):
        client = self._client()
        response = client.put(
            "/admin/quotas",
            json={"defaultMonthlyTokens": 5000, "overrides": {"a@x.co": 100}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"defaultMonthlyTokens": 5000, "overrides": {"a@x.co": 100}}
        )
        bad = client.put("/admin/quotas", json={"defaultMonthlyTokens": -1})
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
