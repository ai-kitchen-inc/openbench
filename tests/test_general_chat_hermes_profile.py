"""Per-agent Hermes profile rendering: minimal by default, isolated by construction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.hermes_profile import (  # noqa: E402
    BUILTIN_TOOLSETS,
    NO_BUNDLED_SKILLS_MARKER,
    HermesMCPServer,
    HermesProfileError,
    HermesProfileSpec,
    main,
    render_config,
    unfilled_env_keys,
    write_profile,
)


def _env(profile_dir: Path) -> dict[str, str]:
    pairs = {}
    for line in (profile_dir / ".env").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        pairs[key] = value
    return pairs


class _TmpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _skill(self, name: str, *, tools: bool = False) -> Path:
        skill_dir = self.root / "src-skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"# {name}\n\nAturan domain {name}.\n\n## Triggers\n- x\n\n## Version\n0.1.0\n",
            encoding="utf-8",
        )
        if tools:
            (skill_dir / "tools.py").write_text("X = 1\n", encoding="utf-8")
        return skill_dir


class TestMinimalDefaults(unittest.TestCase):
    def test_bare_agent_gets_no_tools_no_mcp_no_memory(self):
        config, secrets_needed = render_config(HermesProfileSpec(agent_id="pajak", soul="Saya."))

        self.assertEqual(config["platform_toolsets"], {"api_server": ["no_mcp"]})
        self.assertEqual(config["agent"]["disabled_toolsets"], sorted(BUILTIN_TOOLSETS))
        self.assertNotIn("mcp_servers", config)
        self.assertFalse(config["memory"]["memory_enabled"])
        self.assertFalse(config["memory"]["user_profile_enabled"])
        self.assertEqual(config["skills"]["creation_nudge_interval"], 0)
        self.assertEqual(config["terminal"]["home_mode"], "profile")
        self.assertEqual(config["model"], {"default": "gemini-3.5-flash", "provider": "gemini"})
        self.assertEqual(secrets_needed, [])

    def test_selected_toolsets_are_the_only_ones_enabled(self):
        spec = HermesProfileSpec(
            agent_id="riset", soul="Saya.", toolsets=["web"], memory_enabled=True
        )
        config, _ = render_config(spec)

        self.assertEqual(config["platform_toolsets"]["api_server"], ["web", "memory", "no_mcp"])
        disabled = set(config["agent"]["disabled_toolsets"])
        self.assertEqual(disabled, set(BUILTIN_TOOLSETS) - {"web", "memory"})

    def test_host_access_toolsets_refused_without_opt_in(self):
        for toolset in ("terminal", "file", "browser", "code_execution", "delegation", "cronjob"):
            with self.assertRaises(HermesProfileError, msg=toolset):
                render_config(HermesProfileSpec(agent_id="a", soul="s", toolsets=[toolset]))
        config, _ = render_config(
            HermesProfileSpec(agent_id="a", soul="s", toolsets=["terminal"], allow_host_access=True)
        )
        self.assertIn("terminal", config["platform_toolsets"]["api_server"])

    def test_validation(self):
        bad_specs = [
            HermesProfileSpec(agent_id="Bad Id", soul="s"),
            HermesProfileSpec(agent_id="a", soul="  "),
            HermesProfileSpec(agent_id="a", soul="s", toolsets=["teleport"]),
            HermesProfileSpec(
                agent_id="a",
                soul="s",
                mcp_servers=[
                    HermesMCPServer("db", {"url": "http://x"}),
                    HermesMCPServer("db", {"url": "http://y"}),
                ],
            ),
            HermesProfileSpec(
                agent_id="a", soul="s", mcp_servers=[HermesMCPServer("web", {"url": "http://x"})]
            ),
            HermesProfileSpec(agent_id="a", soul="s", mcp_servers=[HermesMCPServer("db", {})]),
        ]
        for spec in bad_specs:
            with self.assertRaises(HermesProfileError):
                render_config(spec)


class TestMCPRendering(unittest.TestCase):
    def test_mcp_server_is_allow_listed_and_secrets_become_env_refs(self):
        spec = HermesProfileSpec(
            agent_id="keu",
            soul="Saya.",
            mcp_servers=[
                HermesMCPServer(
                    "db",
                    {
                        "transport": "streamable_http",
                        "url": "http://mcp-db:9000/mcp",
                        "headers": {"Authorization": "Bearer ${secret:db.token}"},
                        "timeout_seconds": 30,
                    },
                    include_tools=["query", "list_tables", "query"],
                )
            ],
        )
        config, secrets_needed = render_config(spec)

        server = config["mcp_servers"]["db"]
        self.assertEqual(server["headers"], {"Authorization": "Bearer ${DB_TOKEN}"})
        self.assertEqual(
            server["tools"],
            {"include": ["list_tables", "query"], "resources": False, "prompts": False},
        )
        self.assertEqual(server["sampling"], {"enabled": False})
        self.assertNotIn("timeout_seconds", server)
        self.assertEqual(config["platform_toolsets"]["api_server"], ["db"])
        self.assertEqual(secrets_needed, ["DB_TOKEN"])

    def test_empty_include_list_registers_no_tools(self):
        spec = HermesProfileSpec(
            agent_id="a", soul="s", mcp_servers=[HermesMCPServer("db", {"command": "uvx"})]
        )
        config, _ = render_config(spec)
        self.assertEqual(config["mcp_servers"]["db"]["tools"]["include"], [])


class TestWriteProfile(_TmpCase):
    def test_layout_marker_soul_and_env(self):
        spec = HermesProfileSpec(agent_id="pajak", soul="Saya analis pajak.", port=8650)
        profile_dir = write_profile(self.root / "profiles", spec)

        self.assertTrue((profile_dir / NO_BUNDLED_SKILLS_MARKER).is_file())
        self.assertEqual(
            (profile_dir / "SOUL.md").read_text(encoding="utf-8"), "Saya analis pajak.\n"
        )
        for subdir in ("memories", "sessions", "skills", "home", "workspace"):
            self.assertTrue((profile_dir / subdir).is_dir())
        parsed = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(parsed["platform_toolsets"]["api_server"], ["no_mcp"])
        self.assertNotIn("cwd", parsed["terminal"])
        env = _env(profile_dir)
        self.assertEqual(env["API_SERVER_ENABLED"], "true")
        self.assertEqual(env["API_SERVER_PORT"], "8650")
        self.assertEqual(env["API_SERVER_HOST"], "127.0.0.1")
        self.assertEqual(env["API_SERVER_MODEL_NAME"], "pajak")
        self.assertGreaterEqual(len(env["API_SERVER_KEY"]), 32)
        self.assertEqual(env["GOOGLE_API_KEY"], "")
        self.assertEqual(unfilled_env_keys(profile_dir), ["GOOGLE_API_KEY"])

    def test_rerun_keeps_operator_filled_env_and_state(self):
        spec = HermesProfileSpec(agent_id="pajak", soul="v1")
        profile_dir = write_profile(self.root, spec)
        first_key = _env(profile_dir)["API_SERVER_KEY"]
        env_path = profile_dir / ".env"
        env_path.write_text(
            env_path.read_text(encoding="utf-8").replace(
                "GOOGLE_API_KEY=", "GOOGLE_API_KEY=filled"
            ),
            encoding="utf-8",
        )
        (profile_dir / "memories" / "MEMORY.md").write_text("ingat", encoding="utf-8")

        spec.soul = "v2"
        spec.port = 8700
        write_profile(self.root, spec)

        env = _env(profile_dir)
        self.assertEqual(env["API_SERVER_KEY"], first_key)
        self.assertEqual(env["GOOGLE_API_KEY"], "filled")
        self.assertEqual(env["API_SERVER_PORT"], "8700")
        self.assertEqual((profile_dir / "SOUL.md").read_text(encoding="utf-8"), "v2\n")
        self.assertEqual((profile_dir / "memories" / "MEMORY.md").read_text("utf-8"), "ingat")
        self.assertEqual(unfilled_env_keys(profile_dir), [])

    def test_skills_are_copied_with_frontmatter_and_stale_ones_removed(self):
        rules = self._skill("aturan-pajak")
        spec = HermesProfileSpec(agent_id="pajak", soul="s", skill_dirs=[rules])
        profile_dir = write_profile(self.root / "p", spec)

        skill_md = (profile_dir / "skills" / "aturan-pajak" / "SKILL.md").read_text("utf-8")
        front = yaml.safe_load(skill_md.split("---")[1])
        self.assertEqual(
            front, {"name": "aturan-pajak", "description": "Aturan domain aturan-pajak."}
        )
        parsed = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
        self.assertIn("skills", parsed["platform_toolsets"]["api_server"])

        spec.skill_dirs = []
        write_profile(self.root / "p", spec)
        self.assertEqual(list((profile_dir / "skills").iterdir()), [])

    def test_tool_bearing_skill_is_refused(self):
        spec = HermesProfileSpec(
            agent_id="a", soul="s", skill_dirs=[self._skill("export", tools=True)]
        )
        with self.assertRaises(HermesProfileError):
            write_profile(self.root / "p", spec)

    def test_host_access_pins_cwd_to_own_workspace(self):
        spec = HermesProfileSpec(
            agent_id="ops", soul="s", toolsets=["terminal"], allow_host_access=True
        )
        profile_dir = write_profile(self.root, spec)
        parsed = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(Path(parsed["terminal"]["cwd"]), (profile_dir / "workspace").resolve())


class TestCrossAgentIsolation(_TmpCase):
    """Nothing selected for agent A may appear anywhere in agent B's profile."""

    def _two_agents(self) -> tuple[Path, Path]:
        a = HermesProfileSpec(
            agent_id="agen-a",
            soul="Saya agen A. CANARY-SOUL-A",
            port=8651,
            toolsets=["web"],
            skill_dirs=[self._skill("skill-a")],
            mcp_servers=[
                HermesMCPServer(
                    "mcp-a",
                    {"url": "http://mcp-a/mcp", "headers": {"X-Key": "${secret:a.key}"}},
                    include_tools=["tool_a"],
                )
            ],
            memory_enabled=True,
        )
        b = HermesProfileSpec(
            agent_id="agen-b",
            soul="Saya agen B.",
            port=8652,
            skill_dirs=[self._skill("skill-b")],
            mcp_servers=[
                HermesMCPServer("mcp-b", {"command": "uvx", "args": ["srv-b"]}, ["tool_b"])
            ],
        )
        root = self.root / "profiles"
        return write_profile(root, a), write_profile(root, b)

    def test_profiles_share_no_config_skills_mcp_or_credentials(self):
        dir_a, dir_b = self._two_agents()
        everything_b = "\n".join(
            path.read_text(encoding="utf-8") for path in dir_b.rglob("*") if path.is_file()
        )
        for needle in ("CANARY-SOUL-A", "mcp-a", "tool_a", "skill-a", "A_KEY", "agen-a"):
            self.assertNotIn(needle, everything_b, needle)

        env_a, env_b = _env(dir_a), _env(dir_b)
        self.assertNotEqual(env_a["API_SERVER_KEY"], env_b["API_SERVER_KEY"])
        self.assertNotEqual(env_a["API_SERVER_PORT"], env_b["API_SERVER_PORT"])
        self.assertIn("A_KEY", env_a)
        self.assertNotIn("A_KEY", env_b)
        self.assertNotIn(env_a["API_SERVER_KEY"], everything_b)

        config_b = yaml.safe_load((dir_b / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(list(config_b["mcp_servers"]), ["mcp-b"])
        self.assertEqual(config_b["platform_toolsets"]["api_server"], ["skills", "mcp-b"])
        self.assertIn("web", config_b["agent"]["disabled_toolsets"])
        self.assertIn("memory", config_b["agent"]["disabled_toolsets"])
        self.assertEqual([p.name for p in (dir_b / "skills").iterdir()], ["skill-b"])

    def test_state_directories_are_disjoint(self):
        dir_a, dir_b = self._two_agents()
        for subdir in ("memories", "sessions", "home", "workspace"):
            self.assertNotEqual((dir_a / subdir).resolve(), (dir_b / subdir).resolve())
            self.assertFalse((dir_a / subdir).resolve().is_relative_to(dir_b.resolve()))


class TestSpecFileCli(_TmpCase):
    def test_cli_renders_each_agent_and_rejects_shared_ports(self):
        (self.root / "soul-a.md").write_text("Saya A.", encoding="utf-8")
        spec_path = self.root / "agents.yaml"
        spec_path.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {"id": "agen-a", "soul_file": "soul-a.md", "port": 8661},
                        {"id": "agen-b", "soul": "Saya B.", "port": 8662, "toolsets": ["web"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        out = self.root / "out"
        self.assertEqual(main([str(spec_path), "--out", str(out)]), 0)
        self.assertEqual((out / "agen-a" / "SOUL.md").read_text(encoding="utf-8"), "Saya A.\n")
        self.assertEqual(_env(out / "agen-b")["API_SERVER_PORT"], "8662")

        spec_path.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {"id": "a", "soul": "s", "port": 1},
                        {"id": "b", "soul": "s", "port": 1},
                    ]
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(HermesProfileError):
            main([str(spec_path), "--out", str(out)])

    def test_compose_gives_each_agent_its_own_container_volume_and_network(self):
        spec_path = self.root / "agents.yaml"
        spec_path.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {"id": "agen-a", "soul": "A", "port": 8661},
                        {"id": "agen-b", "soul": "B", "port": 8662},
                    ]
                }
            ),
            encoding="utf-8",
        )
        compose_path = self.root / "docker-compose.hermes.yml"
        main(
            [
                str(spec_path),
                "--out",
                str(self.root / "profiles"),
                "--compose",
                str(compose_path),
                "--bind-ip",
                "10.0.0.9",
            ]
        )
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        a, b = compose["services"]["hermes-agen-a"], compose["services"]["hermes-agen-b"]

        self.assertEqual(a["volumes"], ["./profiles/agen-a:/opt/data"])
        self.assertEqual(b["volumes"], ["./profiles/agen-b:/opt/data"])
        self.assertEqual(a["ports"], ["10.0.0.9:8661:8661"])
        self.assertEqual(a["networks"], ["hermes-agen-a"])
        self.assertEqual(b["networks"], ["hermes-agen-b"])
        self.assertEqual(sorted(compose["networks"]), ["hermes-agen-a", "hermes-agen-b"])
        for service in (a, b):
            self.assertNotIn("env_file", service)
            self.assertNotIn("docker.sock", str(service))
            self.assertIn("v2026.9.14", service["build"]["context"])
        self.assertEqual(_env(self.root / "profiles" / "agen-a")["API_SERVER_HOST"], "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
