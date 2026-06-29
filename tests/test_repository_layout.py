from __future__ import annotations

from pathlib import Path
import unittest


class RepositoryLayoutTests(unittest.TestCase):
    def test_workflows_and_hygiene_files_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in (
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
            ".gitignore",
            "LICENSE",
            "SECURITY.md",
            "CHANGELOG.md",
        ):
            self.assertTrue((root / relative).is_file(), relative)

    def test_release_workflow_publishes_expected_assets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("launcher-v${{ inputs.version }}", workflow)
        self.assertIn("FutonHUB-Launcher.exe", workflow)
        self.assertIn("FutonHUB-Launcher.exe.sha256", workflow)
        self.assertIn("contents: write", workflow)

    def test_main_branch_does_not_track_generated_binaries_by_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("dist/", ignore)
        self.assertIn("build/", ignore)
        self.assertIn("*.spec", ignore)


if __name__ == "__main__":
    unittest.main()
