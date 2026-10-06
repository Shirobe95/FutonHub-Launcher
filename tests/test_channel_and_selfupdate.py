from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from futonhub_auto import flow
from futonhub_auto.channel import CHANNEL, CHANNELS, STABLE
from futonhub_auto.config import LauncherConfig
from futonhub_auto.github_api import GitHubClient, LauncherRelease
from futonhub_auto.paths import AppPaths
from futonhub_auto.self_update import (
    FAILED_FILE,
    OK_MARKER,
    build_replacement_script,
    failed_versions,
    schedule_update,
    write_ok_marker,
)
from futonhub_auto.versioning import parse_release_tag

ROOT = Path(__file__).resolve().parents[1]


def assets(tag: str) -> list[dict]:
    return [
        {"name": "FutonHUB-Launcher.exe", "url": f"{tag}/exe"},
        {"name": "FutonHUB-Launcher.exe.sha256", "url": f"{tag}/sha"},
    ]


class ChannelIsolationTests(unittest.TestCase):
    def test_test_channel_is_fully_separated_from_stable(self) -> None:
        test = CHANNELS["test"]
        for field in ("app_dir_name", "shortcut_name", "registry_key", "erp_branch", "credential_target", "release_tag_prefix"):
            self.assertNotEqual(getattr(test, field), getattr(STABLE, field), field)
        self.assertEqual(test.erp_branch, "test/upgrade-001")
        self.assertEqual(STABLE.erp_branch, "main")

    def test_this_branch_builds_the_test_channel(self) -> None:
        self.assertEqual(CHANNEL.name, "test")
        config = LauncherConfig()
        self.assertEqual(config.branch, "test/upgrade-001")
        self.assertEqual(config.credential_target, "FutonHUB-Test/GitHubReadOnly")
        self.assertEqual(config.release_tag_prefix, "launcher-test-v")
        self.assertTrue(config.release_allow_prerelease)

    def test_install_directory_is_not_the_production_one(self) -> None:
        with patch.dict("os.environ", {"LOCALAPPDATA": "/tmp/lad"}):
            self.assertEqual(AppPaths.default().root.name, "FutonHUB-Test")

    def test_stable_launchers_ignore_test_releases(self) -> None:
        self.assertIsNone(parse_release_tag("launcher-test-v0.13.0"))  # prefijo estable por defecto
        client = GitHubClient("o", "r", "main", require_auth=False)
        client._json = MagicMock(  # type: ignore[method-assign]
            return_value=[{"tag_name": "launcher-test-v9.9.9", "draft": False, "prerelease": True, "assets": assets("t")}]
        )
        self.assertIsNone(client.latest_launcher_release())  # lo que ejecuta un launcher estable

    def test_test_launcher_ignores_stable_releases_and_accepts_prereleases(self) -> None:
        client = GitHubClient("o", "r", "main", require_auth=False)
        client._json = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"tag_name": "launcher-v9.0.0", "draft": False, "prerelease": False, "assets": assets("s")},
                {"tag_name": "launcher-test-v0.14.0", "draft": False, "prerelease": True, "assets": assets("t")},
            ]
        )
        found = client.latest_launcher_release(prefix="launcher-test-v", allow_prerelease=True)
        self.assertEqual(found.tag_name, "launcher-test-v0.14.0")

    def test_workflows_match_their_channel(self) -> None:
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        test = (ROOT / ".github/workflows/release-test.yml").read_text(encoding="utf-8")
        self.assertIn("CHANNEL_NAME", release)
        self.assertIn('"stable"', release)
        self.assertIn("launcher-test-v", test)
        self.assertIn("test/upgrade-001", test)
        self.assertIn("--prerelease", test)
        self.assertIn("--selftest", test)


class SelfUpdateHandshakeTests(unittest.TestCase):
    def script(self, **kw) -> str:
        return build_replacement_script(
            Path(r"C:\F\Launcher\FutonHUB Launcher.exe"), Path(r"C:\T\new.exe"), pid=7, **kw
        )

    def test_script_with_handshake_rolls_back_when_new_exe_does_not_confirm(self) -> None:
        script = self.script(version="0.14.0", state_dir=Path(r"C:\F\State"))
        for fragment in (
            OK_MARKER,
            FAILED_FILE,
            "$ExpectedVersion",
            "-PassThru",
            "$Proc.HasExited",
            "if (-not $Healthy)",
            "Stop-Process -Id $Proc.Id",
            "Move-Item -LiteralPath $Backup -Destination $Target",
            "Add-Content -LiteralPath $FailedFile",
        ):
            self.assertIn(fragment, script)
        self.assertLess(script.index("Start-Process -FilePath $Target"), script.index("Remove-Item -LiteralPath $Backup -Force -ErrorAction"))

    def test_backup_is_kept_until_confirmation(self) -> None:
        script = self.script(version="0.14.0", state_dir=Path(r"C:\F\State"))
        lines = script.splitlines()
        first_delete = next(i for i, line in enumerate(lines) if "Remove-Item -LiteralPath $Backup -Force -ErrorAction" in line)
        healthy_check = next(i for i, line in enumerate(lines) if "if (-not $Healthy)" in line)
        self.assertGreater(first_delete, healthy_check)

    def test_schedule_update_passes_version_and_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            exe = paths.root / "Launcher" / "FutonHUB Launcher.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"old")
            new = paths.downloads / "n.exe"
            new.write_bytes(b"new")
            update = MagicMock(downloaded_exe=new, release=LauncherRelease("0.14.0", "t", "e", "s", ""))
            with patch("futonhub_auto.self_update.IS_WINDOWS", True), patch("futonhub_auto.self_update.subprocess.Popen"):
                script_path = schedule_update(paths, update, pid=99)
            text = script_path.read_text(encoding="utf-8-sig")
            self.assertIn("$ExpectedVersion = '0.14.0'", text)
            self.assertIn(OK_MARKER, text)

    def test_ok_marker_and_failed_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            write_ok_marker(paths, "0.13.0")
            self.assertEqual(json.loads((paths.state / OK_MARKER).read_text())["version"], "0.13.0")
            self.assertEqual(failed_versions(paths), set())
            (paths.state / FAILED_FILE).write_text("0.14.0\r\n0.15.0\n", encoding="utf-8")
            self.assertEqual(failed_versions(paths), {"0.14.0", "0.15.0"})

    def test_flow_skips_a_version_that_already_failed_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            (paths.state / FAILED_FILE).write_text("9.0.0\n")
            release = LauncherRelease("9.0.0", "launcher-test-v9.0.0", "e", "s", "")
            events: list[tuple[str, object]] = []
            started = flow.StartupFlow(paths, LauncherConfig(), lambda e, p: events.append((e, p)), frozen=True, client_factory=lambda *a, **k: MagicMock())
            with patch.object(flow, "find_update", return_value=release), patch.object(flow, "download_update") as download:
                self.assertFalse(started._check_launcher_update())
            download.assert_not_called()
            self.assertTrue(any("se revirtió" in str(p) for _, p in events))

    def test_selftest_writes_result_without_touching_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "st.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "--selftest", str(target)],
                capture_output=True, text=True, timeout=60, cwd=temp,
                env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": temp, "LOCALAPPDATA": str(Path(temp) / "lad")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(target.read_text())
            self.assertTrue(data["ok"])
            self.assertEqual(data["channel"], CHANNEL.name)
            self.assertFalse((Path(temp) / "lad").exists())


if __name__ == "__main__":
    unittest.main()
