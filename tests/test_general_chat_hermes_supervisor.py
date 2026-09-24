"""Managed Hermes: supervisor lifecycle, panel-fields -> profile plan, admin endpoints."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent_store import AgentProfileRecord  # noqa: E402
from general_chat.hermes_profile import HermesProfileSpec  # noqa: E402
from general_chat.hermes_runtime import (  # noqa: E402
    HermesRuntimeConfigError,
    ManagedHermesPlan,
    build_hermes_agent,
    plan_managed_profile,
)
from general_chat.hermes_supervisor import (  # noqa: E402
    RENDER_HASH_FILE,
    HermesEndpoint,
    HermesSupervisor,
    HermesSupervisorError,
    _read_env_file,
)

from openbench.adapters.hermes import HermesAgent  # noqa: E402
from tests.test_general_chat_agent_isolation import _LocalHarness  # noqa: E402

SUP = "general_chat.hermes_supervisor"


def _spec(agent_id: str = "agen-a", soul: str = "Saya A.") -> HermesProfileSpec:
    return HermesProfileSpec(agent_id=agent_id, soul=soul)


class _TmpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class TestSupervisorConfig(_TmpCase):
    def test_from_env_disabled_by_default(self):
        with patch.dict(environ, {}, clear=False):
            environ.pop("GENERAL_CHAT_HERMES_BACKEND", None)
            self.assertIsNone(HermesSupervisor.from_env(self.root))

    def test_from_env_reads_settings(self):
        env = {
            "GENERAL_CHAT_HERMES_BACKEND": "Docker",
            "GENERAL_CHAT_HERMES_IMAGE": "img:1",
            "GENERAL_CHAT_HERMES_NETWORK": "net-x",
        }
        with patch.dict(environ, env, clear=False):
            supervisor = HermesSupervisor.from_env(self.root)
        self.assertEqual(supervisor.backend, "docker")
        self.assertEqual(supervisor.docker_image, "img:1")
        self.assertEqual(supervisor.docker_network, "net-x")
        self.assertEqual(supervisor.root, self.root / "hermes")

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            HermesSupervisor(self.root, backend="k8s")


class TestProcessBackend(_TmpCase):
    def _supervisor(self) -> HermesSupervisor:
        return HermesSupervisor(
            self.root, backend="process", hermes_bin="hermes-x", startup_timeout=5
        )

    def test_ensure_renders_starts_and_returns_own_endpoint(self):
        supervisor = self._supervisor()
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process) as popen,
            patch.object(HermesSupervisor, "_healthy", side_effect=[False, False, True]),
        ):
            endpoint = supervisor.ensure(_spec(), {"GOOGLE_API_KEY": "llm-secret"})

        profile_dir = self.root / "agen-a"
        file_env = _read_env_file(profile_dir)
        self.assertEqual(endpoint.url, f"http://127.0.0.1:{file_env['API_SERVER_PORT']}")
        self.assertEqual(endpoint.api_key, file_env["API_SERVER_KEY"])
        self.assertEqual(file_env["API_SERVER_HOST"], "127.0.0.1")
        # Secrets reach the gateway as environment only — never the profile on disk.
        self.assertNotIn("GOOGLE_API_KEY", file_env)
        on_disk = "".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in profile_dir.rglob("*")
            if p.is_file()
        )
        self.assertNotIn("llm-secret", on_disk)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["hermes-x", "gateway", "run"])
        self.assertEqual(kwargs["env"]["GOOGLE_API_KEY"], "llm-secret")
        self.assertEqual(Path(kwargs["env"]["HERMES_HOME"]), profile_dir.resolve())
        self.assertTrue((profile_dir / RENDER_HASH_FILE).is_file())

    def test_unchanged_render_and_healthy_gateway_is_not_restarted(self):
        supervisor = self._supervisor()
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process) as popen,
            patch.object(HermesSupervisor, "_healthy", return_value=True),
            patch(f"{SUP}._kill_pid") as kill,
        ):
            # First call: no stored hash yet -> start. Second: same render -> adopt.
            first = supervisor.ensure(_spec(), {"GOOGLE_API_KEY": "k"})
            second = supervisor.ensure(_spec(), {"GOOGLE_API_KEY": "k"})
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(first, second)
            # Changed persona -> restart with the new render.
            supervisor.ensure(_spec(soul="Saya A versi 2."), {"GOOGLE_API_KEY": "k"})
            self.assertEqual(popen.call_count, 2)
            kill.assert_called()
            # Rotated secret -> restart too.
            supervisor.ensure(_spec(soul="Saya A versi 2."), {"GOOGLE_API_KEY": "k2"})
            self.assertEqual(popen.call_count, 3)

    def test_two_agents_get_distinct_dirs_ports_and_keys(self):
        supervisor = self._supervisor()
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process),
            patch.object(HermesSupervisor, "_healthy", return_value=True),
            patch(f"{SUP}._port_is_free", return_value=True),
            patch(f"{SUP}._free_port", side_effect=[41001, 41002]),
        ):
            a = supervisor.ensure(_spec("agen-a"), {})
            b = supervisor.ensure(_spec("agen-b", "Saya B."), {})
        self.assertNotEqual(a.url, b.url)
        self.assertNotEqual(a.api_key, b.api_key)
        self.assertNotIn(a.api_key, (self.root / "agen-b" / ".env").read_text(encoding="utf-8"))

    def test_gateway_exit_is_reported(self):
        supervisor = self._supervisor()
        process = MagicMock()
        process.poll.return_value = 3
        process.returncode = 3
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process),
            patch.object(HermesSupervisor, "_healthy", return_value=False),
            self.assertRaises(HermesSupervisorError),
        ):
            supervisor.ensure(_spec(), {})
        self.assertIn("exited", supervisor.status("agen-a")["error"])

    def test_missing_binary_is_a_clear_error(self):
        supervisor = self._supervisor()
        with (
            patch(f"{SUP}.subprocess.Popen", side_effect=FileNotFoundError("nope")),
            patch.object(HermesSupervisor, "_healthy", return_value=False),
            self.assertRaises(HermesSupervisorError) as ctx,
        ):
            supervisor.ensure(_spec(), {})
        self.assertIn("GENERAL_CHAT_HERMES_BIN", str(ctx.exception))

    def test_remove_stops_and_deletes_profile(self):
        supervisor = self._supervisor()
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process),
            patch.object(HermesSupervisor, "_healthy", return_value=True),
            patch(f"{SUP}._kill_pid") as kill,
        ):
            supervisor.ensure(_spec(), {})
            supervisor.remove("agen-a")
        kill.assert_called_once_with(process.pid)
        self.assertFalse((self.root / "agen-a").exists())

    def test_status_of_unrendered_agent(self):
        status = self._supervisor().status("belum-ada")
        self.assertEqual((status["rendered"], status["running"], status["url"]), (False, False, ""))


class TestDockerBackend(_TmpCase):
    def test_container_is_isolated_and_gets_secrets_by_name_only(self):
        supervisor = HermesSupervisor(
            self.root, backend="docker", docker_image="img:1", docker_network="net-h"
        )
        done = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch(f"{SUP}.subprocess.run", return_value=done) as run,
            patch.object(HermesSupervisor, "_healthy", side_effect=[False, True]),
        ):
            endpoint = supervisor.ensure(_spec(), {"GOOGLE_API_KEY": "llm-secret", "DB_TOKEN": "t"})

        self.assertEqual(endpoint.url, "http://hermes-agen-a:8642")
        self.assertEqual(_read_env_file(self.root / "agen-a")["API_SERVER_HOST"], "0.0.0.0")
        rm_call, run_call = run.call_args_list
        self.assertEqual(rm_call.args[0], ["docker", "rm", "-f", "hermes-agen-a"])
        command = run_call.args[0]
        joined = " ".join(command)
        self.assertNotIn("llm-secret", joined)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn("--privileged", joined)
        self.assertIn("--network net-h --network-alias hermes-agen-a", joined)
        self.assertIn("--security-opt no-new-privileges:true", joined)
        self.assertIn(f"{(self.root / 'agen-a').resolve()}:/opt/data", joined)
        self.assertEqual(command.count("-v"), 1)
        self.assertEqual(command[-3:], ["img:1", "gateway", "run"])
        self.assertEqual(
            [command[i + 1] for i, part in enumerate(command) if part == "-e"],
            ["DB_TOKEN", "GOOGLE_API_KEY"],
        )
        self.assertEqual(run_call.kwargs["env"]["GOOGLE_API_KEY"], "llm-secret")

    def test_docker_failure_surfaces_stderr(self):
        supervisor = HermesSupervisor(self.root, backend="docker")
        results = [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=125, stdout="", stderr="no such image"),
        ]
        with (
            patch(f"{SUP}.subprocess.run", side_effect=results),
            patch.object(HermesSupervisor, "_healthy", return_value=False),
            self.assertRaises(HermesSupervisorError) as ctx,
        ):
            supervisor.ensure(_spec(), {})
        self.assertIn("no such image", str(ctx.exception))

    def test_shutdown_leaves_containers_running(self):
        supervisor = HermesSupervisor(self.root, backend="docker")
        with patch(f"{SUP}.subprocess.run") as run:
            supervisor.shutdown()
        run.assert_not_called()


def _server(name, config, *, tools=(("query", True), ("drop", False)), enabled=True, sid="s1"):
    return SimpleNamespace(
        id=sid,
        name=name,
        enabled=enabled,
        config=config,
        tools=[SimpleNamespace(name=n, enabled=e) for n, e in tools],
    )


class TestManagedPlan(_TmpCase):
    def _skill(self, name: str, *, tools: bool = False) -> Path:
        skill_dir = self.root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n\nAturan {name}.\n", encoding="utf-8")
        if tools:
            (skill_dir / "tools.py").write_text("X = 1\n", encoding="utf-8")
        return skill_dir

    def _plan(self, profile, **kwargs) -> ManagedHermesPlan:
        defaults = {
            "soul": "Saya.",
            "skill_dirs": [],
            "mcp_servers": [],
            "secret_lookup": lambda server_id, key: None,
            "backend": "process",
        }
        with patch.dict(environ, {"GOOGLE_API_KEY": "llm", "MCP_DB_URL": "postgres://x"}):
            return plan_managed_profile(profile, **{**defaults, **kwargs})

    def test_panel_fields_map_to_spec_and_llm_key_goes_to_env(self):
        profile = AgentProfileRecord(id="keu", name="Keu", model="gemini-2.5-pro")
        profile.hermes_memory = True
        plan = self._plan(profile, soul="Saya analis.", default_model="gemini-3.5-flash")
        self.assertEqual(plan.spec.agent_id, "keu")
        self.assertEqual(plan.spec.model, "gemini-2.5-pro")
        self.assertTrue(plan.spec.memory_enabled)
        self.assertEqual(plan.spec.toolsets, [])
        self.assertEqual(plan.env, {"GOOGLE_API_KEY": "llm"})
        self.assertEqual(plan.warnings, [])

    def test_tool_skills_are_skipped_with_a_warning(self):
        plan = self._plan(
            AgentProfileRecord(id="a", name="A"),
            skill_dirs=[self._skill("aturan"), self._skill("export-excel", tools=True)],
        )
        self.assertEqual([p.name for p in plan.spec.skill_dirs], ["aturan"])
        self.assertTrue(any("export-excel" in w for w in plan.warnings))

    def test_mcp_only_enabled_tools_and_secrets_resolved_into_env(self):
        server = _server(
            "DB Server",
            {
                "url": "http://mcp-db/mcp",
                "headers": {"Authorization": "Bearer ${secret:db.token}", "X-Url": "${MCP_DB_URL}"},
            },
        )
        lookups = []

        def lookup(server_id, key):
            lookups.append((server_id, key))
            return "tok-123"

        plan = self._plan(
            AgentProfileRecord(id="a", name="A"), mcp_servers=[server], secret_lookup=lookup
        )
        rendered = plan.spec.mcp_servers[0]
        self.assertEqual(rendered.name, "db-server")
        self.assertEqual(rendered.include_tools, ["query"])
        self.assertEqual(lookups, [("s1", "db.token")])
        self.assertEqual(plan.env["DB_TOKEN"], "tok-123")
        self.assertEqual(plan.env["MCP_DB_URL"], "postgres://x")

    def test_unrunnable_mcp_servers_are_skipped_with_warnings(self):
        servers = [
            _server("openbench", {"transport": "in-memory"}, sid="internal"),
            _server("mati", {"url": "http://x"}, enabled=False, sid="s2"),
            _server("db-docker", {"command": "docker", "args": ["run", "-i", "img"]}, sid="s3"),
        ]
        docker_plan = self._plan(
            AgentProfileRecord(id="a", name="A"), mcp_servers=servers, backend="docker"
        )
        self.assertEqual(docker_plan.spec.mcp_servers, [])
        self.assertEqual(len(docker_plan.warnings), 3)
        # A local process backend can still spawn docker-based stdio servers.
        process_plan = self._plan(
            AgentProfileRecord(id="a", name="A"), mcp_servers=servers, backend="process"
        )
        self.assertEqual([s.name for s in process_plan.spec.mcp_servers], ["db-docker"])

    def test_missing_secret_and_llm_key_are_reported(self):
        server = _server("db", {"url": "http://x", "headers": {"A": "${secret:tok}"}})
        with patch.dict(environ, {}, clear=False):
            environ.pop("GOOGLE_API_KEY", None)
            plan = plan_managed_profile(
                AgentProfileRecord(id="a", name="A"),
                soul="s",
                skill_dirs=[],
                mcp_servers=[server],
                secret_lookup=lambda server_id, key: None,
                backend="process",
            )
        self.assertNotIn("GOOGLE_API_KEY", plan.env)
        self.assertEqual(len(plan.warnings), 2)


class TestBuildManagedAgent(unittest.TestCase):
    def test_managed_build_uses_supervisor_endpoint(self):
        supervisor = MagicMock()
        supervisor.ensure.return_value = HermesEndpoint("http://127.0.0.1:41001", "key-a")
        profile = AgentProfileRecord(id="agen-a", name="A", runtime="hermes")
        plan = ManagedHermesPlan(spec=_spec(), env={"GOOGLE_API_KEY": "k"})

        agent = build_hermes_agent(profile, supervisor=supervisor, plan=plan)

        self.assertIsInstance(agent, HermesAgent)
        self.assertEqual(agent.adapter.base_url, "http://127.0.0.1:41001")
        self.assertEqual(agent.adapter._api_key, "key-a")
        supervisor.ensure.assert_called_once_with(plan.spec, plan.env)

    def test_managed_build_without_supervisor_fails(self):
        profile = AgentProfileRecord(id="agen-a", name="A", runtime="hermes")
        with self.assertRaises(HermesRuntimeConfigError):
            build_hermes_agent(profile)


@pytest.mark.integration
class TestManagedHermesInApp(_LocalHarness):
    def _managed_client(self):
        patcher = patch.dict(
            environ,
            {"GENERAL_CHAT_HERMES_BACKEND": "process", "GOOGLE_API_KEY": "llm-k"},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return self._client()

    def test_managed_agent_needs_no_url_and_is_built_through_the_supervisor(self):
        client = self._managed_client()
        supervisor = client.app.state.hermes_supervisor
        self.assertIsNotNone(supervisor)
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes", hermesMemory=True)

        endpoint = HermesEndpoint("http://127.0.0.1:41001", "key-a")
        with patch.object(supervisor, "ensure", return_value=endpoint) as ensure:
            agent = client.app.state.agent_registry.get(agent_id)

        self.assertIsInstance(agent, HermesAgent)
        spec, env = ensure.call_args.args
        self.assertEqual(spec.agent_id, agent_id)
        self.assertTrue(spec.memory_enabled)
        self.assertTrue(spec.soul.strip())
        self.assertEqual(env["GOOGLE_API_KEY"], "llm-k")

    def test_status_and_start_endpoints(self):
        client = self._managed_client()
        supervisor = client.app.state.hermes_supervisor
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes")

        status = client.get(f"/admin/agents/{agent_id}/hermes").json()
        self.assertTrue(status["managed"])
        self.assertFalse(status["running"])
        self.assertNotIn("llm-k", str(status))

        endpoint = HermesEndpoint("http://127.0.0.1:41001", "key-a")
        with patch.object(supervisor, "ensure", return_value=endpoint) as ensure:
            started = client.post(f"/admin/agents/{agent_id}/hermes/start")
        self.assertEqual(started.status_code, 200, started.text)
        ensure.assert_called_once()
        self.assertNotIn("key-a", started.text)

        with patch.object(supervisor, "ensure", side_effect=HermesSupervisorError("boom")):
            failed = client.post(f"/admin/agents/{agent_id}/hermes/start")
        self.assertEqual(failed.status_code, 502)

        plain_id = self._add_agent(client, "Agen Biasa")
        self.assertEqual(client.post(f"/admin/agents/{plain_id}/hermes/start").status_code, 400)
        self.assertFalse(client.get(f"/admin/agents/{plain_id}/hermes").json()["managed"])

    def test_leaving_hermes_stops_the_gateway_and_delete_removes_the_profile(self):
        client = self._managed_client()
        supervisor = client.app.state.hermes_supervisor
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes")

        with patch.object(supervisor, "stop") as stop:
            client.put(f"/admin/agents/{agent_id}", json={"guardrails": "Sopan."})
            stop.assert_not_called()  # still managed Hermes
            client.put(f"/admin/agents/{agent_id}", json={"runtime": ""})
            stop.assert_called_once_with(agent_id)

        with patch.object(supervisor, "remove") as remove:
            self.assertEqual(client.delete(f"/admin/agents/{agent_id}").status_code, 200)
        remove.assert_called_once_with(agent_id)

    def test_without_backend_a_url_less_hermes_agent_is_rejected(self):
        environ.pop("GENERAL_CHAT_HERMES_BACKEND", None)
        client = self._client()
        self.assertIsNone(client.app.state.hermes_supervisor)
        response = client.post(
            "/admin/agents", json={"name": "Y", "description": "y.", "runtime": "hermes"}
        )
        self.assertEqual(response.status_code, 400)


class TestRenderedManagedProfile(_TmpCase):
    def test_managed_profile_stays_minimal(self):
        supervisor = HermesSupervisor(self.root, backend="process", startup_timeout=5)
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch(f"{SUP}.subprocess.Popen", return_value=process),
            patch.object(HermesSupervisor, "_healthy", return_value=True),
        ):
            supervisor.ensure(_spec(), {"GOOGLE_API_KEY": "k"})
        config = yaml.safe_load((self.root / "agen-a" / "config.yaml").read_text("utf-8"))
        self.assertEqual(config["platform_toolsets"]["api_server"], ["no_mcp"])
        self.assertIn("terminal", config["agent"]["disabled_toolsets"])


if __name__ == "__main__":
    unittest.main()
