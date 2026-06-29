from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import MemoryCredentialStore
from futonhub_auto.logging_utils import redact
from futonhub_auto.paths import AppPaths


class CoreTests(unittest.TestCase):
    def test_paths_create_expected_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            paths.ensure()
            for item in (
                paths.root,
                paths.staging,
                paths.rollback,
                paths.state,
                paths.downloads,
                paths.config,
                paths.logs,
                paths.runtime,
            ):
                self.assertTrue(item.is_dir())

    def test_config_is_created_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "launcher.json"
            config = LauncherConfig.load_or_create(path)
            raw = path.read_text(encoding="utf-8")
            self.assertEqual(config.branch, "refactor/modularizacion-v1")
            self.assertNotIn("token", raw.casefold())

    def test_memory_credentials(self) -> None:
        store = MemoryCredentialStore()
        store.write("x", "secret")
        self.assertEqual(store.read("x"), "secret")
        store.delete("x")
        self.assertIsNone(store.read("x"))

    def test_redact(self) -> None:
        self.assertEqual(redact("abc TOKEN xyz", "TOKEN"), "abc *** xyz")
