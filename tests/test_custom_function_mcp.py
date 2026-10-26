"""Tests for the custom-function MCP (store, runner, service)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1] / "mcp" / "custom-function-mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from app import runner, service, store  # noqa: E402

pytestmark = pytest.mark.integration


def _write_function(root: Path, name: str, code: str, description: str = "") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.py").write_text(code, encoding="utf-8")
    (root / f"{name}.json").write_text(
        json.dumps({"name": name, "description": description, "created_at": "2026-07-02"}),
        encoding="utf-8",
    )


class _FunctionsDirMixin(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "functions"
        env_patch = patch.dict("os.environ", {"CUSTOM_FN_DIR": str(self.root)})
        env_patch.start()
        self.addCleanup(env_patch.stop)


class TestStore(_FunctionsDirMixin):
    def test_validate_name_accepts_identifiers(self):
        self.assertEqual(store.validate_name("add_numbers"), "add_numbers")
        self.assertEqual(store.validate_name("_private2"), "_private2")

    def test_validate_name_rejects_bad_names(self):
        for bad in ("", "1abc", "has-dash", "Has_Upper", "a" * 65, "../evil", "a.b"):
            with self.assertRaises(ValueError, msg=bad):
                store.validate_name(bad)

    def test_list_meta_empty_when_dir_missing(self):
        self.assertEqual(store.list_meta(), [])

    def test_list_and_load_round_trip(self):
        _write_function(self.root, "add", "def add(a, b):\n    return a + b\n", "adds")
        metas = store.list_meta()
        self.assertEqual([m["name"] for m in metas], ["add"])
        self.assertEqual(metas[0]["description"], "adds")
        code, meta = store.load("add")
        self.assertIn("def add", code)
        self.assertEqual(meta["name"], "add")

    def test_load_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            store.load("nope")

    def test_list_meta_skips_orphan_meta(self):
        # meta without a .py must not be listed
        self.root.mkdir(parents=True)
        (self.root / "ghost.json").write_text(json.dumps({"name": "ghost"}), encoding="utf-8")
        self.assertEqual(store.list_meta(), [])


class TestRunner(_FunctionsDirMixin):
    def test_run_success(self):
        _write_function(self.root, "add", "def add(a, b):\n    return a + b\n")
        payload = runner.run("add", {"a": 2, "b": 3})
        self.assertEqual(payload, {"ok": True, "result": 5, "stdout": ""})

    def test_run_captures_stdout(self):
        _write_function(self.root, "noisy", "def noisy():\n    print('hi')\n    return 1\n")
        payload = runner.run("noisy", {})
        self.assertEqual(payload["result"], 1)
        self.assertEqual(payload["stdout"], "hi\n")

    def test_run_non_jsonable_result_falls_back_to_repr(self):
        _write_function(self.root, "obj", "def obj():\n    return {1, 2}\n")
        payload = runner.run("obj", {})
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["result"], str)

    def test_run_missing_callable_raises(self):
        _write_function(self.root, "broken", "x = 1\n")
        with self.assertRaises(ValueError):
            runner.run("broken", {})

    def test_main_reports_errors_as_json(self):
        _write_function(self.root, "boom", "def boom():\n    raise RuntimeError('nope')\n")
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runner.main(["boom", "{}"])
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("RuntimeError", payload["error"])


class TestService(_FunctionsDirMixin):
    def test_run_function_subprocess_round_trip(self):
        _write_function(self.root, "add", "def add(a, b):\n    return a + b\n")
        payload = service.run_function("add", {"a": 2, "b": 3})
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["result"], 5)

    def test_run_function_error_propagates(self):
        _write_function(self.root, "boom", "def boom():\n    raise RuntimeError('nope')\n")
        payload = service.run_function("boom", {})
        self.assertFalse(payload["ok"])
        self.assertIn("RuntimeError", payload["error"])

    def test_run_function_timeout(self):
        _write_function(
            self.root, "slow", "import time\ndef slow():\n    time.sleep(10)\n"
        )
        with patch.dict("os.environ", {"CUSTOM_FN_TIMEOUT_SECONDS": "1"}):
            payload = service.run_function("slow", {})
        self.assertFalse(payload["ok"])
        self.assertIn("timed out", payload["error"])

    def test_list_and_describe(self):
        _write_function(self.root, "add", "def add(a, b):\n    return a + b\n", "adds")
        self.assertEqual(
            [m["name"] for m in service.list_functions()["functions"]], ["add"]
        )
        described = service.describe_function("add")
        self.assertIn("def add", described["code"])
        self.assertEqual(described["meta"]["description"], "adds")


if __name__ == "__main__":
    unittest.main()
