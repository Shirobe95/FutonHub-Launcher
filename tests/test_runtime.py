from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from futonhub_auto.config import LauncherConfig
from futonhub_auto.python_runtime import sha256_file


class RuntimeTests(unittest.TestCase):
    def test_official_python_metadata_is_pinned(self) -> None:
        config = LauncherConfig()
        self.assertEqual(config.python_version, "3.13.14")
        self.assertTrue(
            config.python_installer_url.startswith("https://www.python.org/")
        )
        self.assertEqual(len(config.python_installer_sha256), 64)

    def test_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_python_has_no_fixed_upper_bound(self) -> None:
        import inspect
        from futonhub_auto import python_runtime
        source = inspect.getsource(python_runtime._valid_python)
        self.assertIn("sys.version_info>=(3,11)", source.replace(" ", ""))
        self.assertNotIn("sys.version_info <", source)
