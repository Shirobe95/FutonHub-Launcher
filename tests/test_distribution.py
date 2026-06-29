from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import unittest

from futonhub_auto import LAUNCHER_VERSION
from futonhub_auto.config import LauncherConfig
from futonhub_auto.desktop import create_shortcuts
from futonhub_auto.github_api import GitHubClient, LauncherRelease
from futonhub_auto.paths import AppPaths
from futonhub_auto.self_update import (
    build_replacement_script,
    download_update,
    find_update,
)
from futonhub_auto.uninstall import build_cleanup_script


class FakeReleaseClient:
    def __init__(self, release: LauncherRelease | None) -> None:
        self.release = release

    def latest_launcher_release(self) -> LauncherRelease | None:
        return self.release


class FakeDownloadClient:
    def __init__(self, executable: bytes) -> None:
        self.executable = executable

    def download_launcher_asset(self, url, destination, progress=None):
        if url == "exe":
            destination.write_bytes(self.executable)
        else:
            digest = hashlib.sha256(self.executable).hexdigest()
            destination.write_text(
                f"{digest}  FutonHUB-Launcher.exe\n", encoding="utf-8"
            )
        return destination


class DistributionTests(unittest.TestCase):
    def test_version_and_build_identity_assets_are_current(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(LAUNCHER_VERSION, "0.12.0")
        build = (root / "build_launcher.bat").read_text(encoding="ascii")
        self.assertIn('--icon "assets\\futonhub.ico"', build)
        self.assertIn('--version-file "assets\\version_info.txt"', build)
        self.assertIn('--add-data "assets\\launcher_icon.png;assets"', build)
        self.assertTrue((root / "assets/futonhub.ico.b64").is_file())
        self.assertTrue((root / "assets/launcher_icon.png.b64").is_file())
        self.assertIn('certutil -decode "assets\\futonhub.ico.b64"', build)
        self.assertIn('certutil -decode "assets\\launcher_icon.png.b64"', build)
        info = (root / "assets/version_info.txt").read_text(encoding="utf-8")
        self.assertIn("FutonHUB Launcher", info)
        self.assertIn("0.12.0", info)

    def test_self_update_defaults_to_enabled(self) -> None:
        self.assertTrue(LauncherConfig().self_update_enabled)


    def test_launcher_release_repository_is_separate_and_public(self) -> None:
        config = LauncherConfig()
        self.assertEqual(config.repository, "FutonEspaiHUB")
        self.assertEqual(config.launcher_repository, "FutonHub-Launcher")
        self.assertNotEqual(config.repository, config.launcher_repository)

    def test_public_release_client_omits_private_authorization_header(self) -> None:
        client = GitHubClient(
            "Shirobe95",
            "FutonHub-Launcher",
            "main",
            require_auth=False,
        )
        request = client._request("https://api.github.com/example")
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertNotIn("authorization", headers)
        self.assertEqual(headers["accept"], "application/vnd.github+json")

    def test_find_update_only_returns_newer_release(self) -> None:
        newer = LauncherRelease("0.12.0", "launcher-v0.12.0", "exe", "sha", "")
        same = LauncherRelease("0.11.0", "launcher-v0.11.0", "exe", "sha", "")
        self.assertEqual(find_update(FakeReleaseClient(newer), "0.11.0"), newer)
        self.assertIsNone(find_update(FakeReleaseClient(same), "0.11.0"))


    def test_github_release_discovery_uses_launcher_tag_and_assets(self) -> None:
        client = GitHubClient("owner", "repo", "branch", "token")
        client._json = MagicMock(return_value=[
            {
                "tag_name": "launcher-v0.12.1",
                "draft": False,
                "prerelease": False,
                "published_at": "2026-06-23T00:00:00Z",
                "assets": [
                    {"name": "FutonHUB-Launcher.exe", "url": "asset-exe"},
                    {
                        "name": "FutonHUB-Launcher.exe.sha256",
                        "url": "asset-sha",
                    },
                ],
            }
        ])
        release = client.latest_launcher_release()
        self.assertIsNotNone(release)
        assert release is not None
        self.assertEqual(release.version, "0.12.1")
        self.assertEqual(release.asset_url, "asset-exe")

    def test_non_launcher_releases_are_ignored(self) -> None:
        client = GitHubClient("owner", "repo", "branch", "token")
        client._json = MagicMock(return_value=[
            {"tag_name": "v2.0.0", "draft": False, "prerelease": False, "assets": []}
        ])
        self.assertIsNone(client.latest_launcher_release())

    def test_launcher_download_requires_matching_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            paths.ensure()
            release = LauncherRelease("0.12.0", "launcher-v0.12.0", "exe", "sha", "")
            update = download_update(
                FakeDownloadClient(b"future launcher"),
                release,
                paths,
                lambda _text: None,
            )
            self.assertTrue(update.downloaded_exe.is_file())
            self.assertEqual(
                update.sha256,
                hashlib.sha256(b"future launcher").hexdigest(),
            )

    def test_replacement_script_is_transactional_and_restarts(self) -> None:
        script = build_replacement_script(
            Path(r"C:\FutonHUB\Launcher\FutonHUB Launcher.exe"),
            Path(r"C:\Temp\FutonHUB-Launcher.exe"),
            pid=321,
        )
        self.assertIn("Wait-Process -Id $LauncherPid", script)
        self.assertIn(".previous", script)
        self.assertIn("Start-Process -FilePath $Target", script)
        self.assertIn("Move-Item -LiteralPath $Backup -Destination $Target", script)

    def test_uninstall_removes_both_shortcuts_and_registry_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            script = build_cleanup_script(paths, pid=123)
        self.assertIn("$DesktopShortcut", script)
        self.assertIn("$StartShortcut", script)
        self.assertIn("CurrentVersion\\Uninstall\\FutonHUB", script)

    def test_shortcut_creation_targets_desktop_and_start_menu(self) -> None:
        executable = Path(r"C:\FutonHUB\Launcher\FutonHUB Launcher.exe")
        with patch("futonhub_auto.desktop.IS_WINDOWS", True), patch(
            "futonhub_auto.desktop.subprocess.run"
        ) as run:
            create_shortcuts(executable)
        command = run.call_args.args[0]
        script = command[-1]
        self.assertIn("GetFolderPath('Desktop')", script)
        self.assertIn("GetFolderPath('Programs')", script)
        self.assertIn("IconLocation", script)


if __name__ == "__main__":
    unittest.main()
