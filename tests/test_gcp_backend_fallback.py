"""GoogleCloudStorageBackend local-fallback roots at the persistent volume.

When no Postgres is configured, sessions/memory fall back to a local backend.
That backend must live on GENERAL_CHAT_STORAGE_ROOT (the mounted, persistent
volume) so chat history survives container restarts — not an ephemeral tempdir.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openbench.integrations.gcp.backend import GoogleCloudStorageBackend


class TestLocalFallbackRoot(unittest.TestCase):
    def test_from_env_roots_local_at_storage_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "GENERAL_CHAT_GCP_BUCKET": "some-bucket",
                "GENERAL_CHAT_STORAGE_ROOT": tmp,
            }
            with mock.patch.dict(os.environ, env, clear=True):
                backend = GoogleCloudStorageBackend.from_env()
            # No DATABASE_URL → local fallback rooted at the persistent volume.
            self.assertIsNone(backend.database_url)
            self.assertEqual(backend._local.root, Path(tmp).resolve())

    def test_from_env_defaults_to_tempdir_when_unset(self):
        env = {"GENERAL_CHAT_GCP_BUCKET": "some-bucket"}
        with mock.patch.dict(os.environ, env, clear=True):
            backend = GoogleCloudStorageBackend.from_env()
        # Falls back to the tempdir default (dev/tests) when no root configured.
        self.assertIn("openbench-gcp-local", str(backend._local.root))


if __name__ == "__main__":
    unittest.main()
