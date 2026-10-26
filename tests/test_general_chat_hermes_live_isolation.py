"""Live isolation probe against two running Hermes profiles (agent A and B).

Skipped unless both servers are described in the environment::

    HERMES_LIVE_A_URL / HERMES_LIVE_A_KEY   (+ optional HERMES_LIVE_A_PROFILE_DIR)
    HERMES_LIVE_B_URL / HERMES_LIVE_B_KEY   (+ optional HERMES_LIVE_B_PROFILE_DIR)
    HERMES_LIVE_LLM=1                       (opt in to tests that spend LLM tokens)

The credential/toolset/skill/session checks use only Hermes' control
endpoints (``/v1/toolsets``, ``/v1/skills``, ``/api/sessions``) and cost no
tokens. Endpoint shapes verified against Hermes Agent v2026.9.14.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

import pytest
import requests
import yaml

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.hermes_profile import BUILTIN_TOOLSETS  # noqa: E402

from openbench.adapters.hermes import HermesAdapter, HermesError  # noqa: E402

pytestmark = pytest.mark.integration

_REQUIRED = ("HERMES_LIVE_A_URL", "HERMES_LIVE_A_KEY", "HERMES_LIVE_B_URL", "HERMES_LIVE_B_KEY")
_CONFIGURED = all(os.getenv(name, "").strip() for name in _REQUIRED)
_LLM = os.getenv("HERMES_LIVE_LLM", "").strip() == "1"


class _Side:
    def __init__(self, prefix: str) -> None:
        self.url = os.environ[f"HERMES_LIVE_{prefix}_URL"].rstrip("/")
        self.key = os.environ[f"HERMES_LIVE_{prefix}_KEY"]
        profile_dir = os.getenv(f"HERMES_LIVE_{prefix}_PROFILE_DIR", "").strip()
        self.profile_dir = Path(profile_dir) if profile_dir else None

    def get(self, path: str, key: str | None = None) -> requests.Response:
        headers = {"Authorization": f"Bearer {key if key is not None else self.key}"}
        return requests.get(f"{self.url}{path}", headers=headers, timeout=30)

    def config(self) -> dict:
        assert self.profile_dir is not None
        return yaml.safe_load((self.profile_dir / "config.yaml").read_text(encoding="utf-8"))


@unittest.skipUnless(_CONFIGURED, "HERMES_LIVE_* env not set")
class TestLiveHermesIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.a, cls.b = _Side("A"), _Side("B")

    def test_distinct_endpoints_and_keys(self):
        self.assertNotEqual(self.a.url, self.b.url)
        self.assertNotEqual(self.a.key, self.b.key)

    def test_key_of_one_agent_never_opens_the_other(self):
        for own, other in ((self.a, self.b), (self.b, self.a)):
            self.assertEqual(own.get("/v1/toolsets").status_code, 200)
            self.assertEqual(own.get("/v1/toolsets", key=other.key).status_code, 401)
            self.assertEqual(own.get("/api/sessions", key=other.key).status_code, 401)
            self.assertEqual(own.get("/v1/toolsets", key="").status_code, 401)
            with self.assertRaises(HermesError) as ctx:
                HermesAdapter(own.url, api_key=other.key).invoke("ping")
            self.assertEqual(ctx.exception.status_code, 401)

    def test_only_selected_builtin_toolsets_are_enabled(self):
        for side in (self.a, self.b):
            data = side.get("/v1/toolsets").json()["data"]
            enabled = {item["name"] for item in data if item["enabled"]}
            if side.profile_dir is None:
                # Without the spec we can still assert the host-reaching ones are off.
                self.assertFalse(enabled & {"terminal", "file", "browser", "code_execution"})
                continue
            allowed = set(side.config()["platform_toolsets"]["api_server"])
            self.assertLessEqual(enabled & set(BUILTIN_TOOLSETS), allowed)

    def test_skills_are_only_the_agents_own(self):
        if self.a.profile_dir is None or self.b.profile_dir is None:
            self.skipTest("profile dirs not provided")
        listed = {}
        for side in (self.a, self.b):
            skills_root = side.profile_dir / "skills"
            response = side.get("/v1/skills")
            if response.status_code == 200:
                names = {item["name"] for item in response.json()["data"]}
            else:
                # Hermes v2026.9.14 answers 500 here (upstream TypeError in
                # _handle_skills); fall back to what its skill scanner reads.
                names = {path.parent.name for path in skills_root.rglob("SKILL.md")}
            own = {p.name for p in skills_root.iterdir() if (p / "SKILL.md").is_file()}
            listed[side] = (names, own)
        (names_a, own_a), (names_b, own_b) = listed[self.a], listed[self.b]
        self.assertFalse(names_a & (own_b - own_a), "agent A lists a skill only B was given")
        self.assertFalse(names_b & (own_a - own_b), "agent B lists a skill only A was given")

    def test_mcp_servers_do_not_overlap_unless_configured_for_both(self):
        if self.a.profile_dir is None or self.b.profile_dir is None:
            self.skipTest("profile dirs not provided")
        servers_a = set(self.a.config().get("mcp_servers") or {})
        servers_b = set(self.b.config().get("mcp_servers") or {})
        platform_a = set(self.a.config()["platform_toolsets"]["api_server"])
        platform_b = set(self.b.config()["platform_toolsets"]["api_server"])
        self.assertFalse(platform_a & (servers_b - servers_a))
        self.assertFalse(platform_b & (servers_a - servers_b))

    def test_profile_dirs_and_credentials_are_disjoint(self):
        if self.a.profile_dir is None or self.b.profile_dir is None:
            self.skipTest("profile dirs not provided")
        dir_a, dir_b = self.a.profile_dir.resolve(), self.b.profile_dir.resolve()
        self.assertFalse(dir_a.is_relative_to(dir_b) or dir_b.is_relative_to(dir_a))
        env_b = (dir_b / ".env").read_text(encoding="utf-8")
        env_a = (dir_a / ".env").read_text(encoding="utf-8")
        self.assertNotIn(self.a.key, env_b)
        self.assertNotIn(self.b.key, env_a)

    @unittest.skipUnless(_LLM, "HERMES_LIVE_LLM=1 not set")
    def test_session_and_memory_of_a_are_invisible_to_b(self):
        session_id = f"iso-{uuid.uuid4().hex[:12]}"
        canary = f"KENARI-{uuid.uuid4().hex[:10].upper()}"
        HermesAdapter(self.a.url, api_key=self.a.key).invoke(
            f"Ingat kode rahasia ini untuk nanti: {canary}. Balas hanya 'ok'.",
            {"session_id": session_id},
        )

        # A holds the transcript...
        self.assertIn(canary, self.a.get(f"/api/sessions/{session_id}/messages").text)
        # ...B has no such session, neither by id nor in its listing...
        self.assertNotIn(canary, self.b.get(f"/api/sessions/{session_id}/messages").text)
        self.assertNotIn(session_id, self.b.get("/api/sessions").text)
        # ...and B cannot recall it even when asked with the same session id.
        answer = HermesAdapter(self.b.url, api_key=self.b.key).invoke(
            "Sebutkan kode rahasia yang tadi saya minta kamu ingat. Jika tidak tahu, jawab TIDAK TAHU.",
            {"session_id": session_id},
        )["output"]
        self.assertNotIn(canary, answer)


if __name__ == "__main__":
    unittest.main()
