from __future__ import annotations

from pathlib import Path
import unittest


class CleanPackageTests(unittest.TestCase):
    def test_no_release_manager_or_private_material(self) -> None:
        root = Path(__file__).resolve().parents[1]
        names = [path.name.casefold() for path in root.rglob("*") if path.is_file()]
        self.assertNotIn("release_manager.py", names)
        self.assertFalse(any(name.endswith(".pem") for name in names))
        self.assertFalse(any(name == ".env" for name in names))

    def test_only_two_admin_batch_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        batch_files = sorted(path.name for path in root.glob("*.bat"))
        self.assertEqual(batch_files, ["build_launcher.bat", "run_tests.bat"])
