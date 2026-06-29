from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from futonhub_auto.bootstrap import launcher_install_path
from futonhub_auto.paths import AppPaths


class BootstrapBuildTests(unittest.TestCase):
    def test_launcher_target_is_under_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            self.assertEqual(
                launcher_install_path(paths),
                paths.root / "Launcher/FutonHUB Launcher.exe",
            )

    def test_build_is_onefile_and_windowed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "build_launcher.bat").read_text(encoding="utf-8")
        self.assertIn("--onefile", text)
        self.assertIn("--windowed", text)

    def test_production_code_does_not_execute_git(self) -> None:
        root = Path(__file__).resolve().parents[1] / "futonhub_auto"
        content = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.glob("*.py")
        ).casefold()
        self.assertNotIn('"git"', content)
        self.assertNotIn("git.exe", content)
