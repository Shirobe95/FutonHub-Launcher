from __future__ import annotations

import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from futonhub_auto import transaction as T
from futonhub_auto.archive import safe_extract_snapshot
from futonhub_auto.config import LauncherConfig
from futonhub_auto.deployment import create_runtime
from futonhub_auto.errors import AlreadyRunningError, DownloadError, ValidationError
from futonhub_auto.github_api import CommitInfo, GitHubClient
from futonhub_auto.locking import update_lock
from futonhub_auto.paths import AppPaths
from futonhub_auto.python_runtime import RuntimeResult
from futonhub_auto.transaction import DirectGitUpdater

REQUIRED = (
    "GestorWoo/gestorwoo.py",
    "GestorWoo/src/futonhub/app/cli.py",
    "GestorWoo/src/futonhub/ui/erp/prototype.py",
    "CalculoCoste/coste_pedido.py",
    "requirements_erp.txt",
)


def build_zip(directory: Path, sha: str, extra: dict[str, str] | None = None) -> Path:
    path = directory / f"{sha}.zip"
    with zipfile.ZipFile(path, "w") as handle:
        for name in REQUIRED:
            handle.writestr(f"Owner-Repo-{sha[:7]}/{name}", f"# {sha}\n" * 40)
        for name, data in (extra or {}).items():
            handle.writestr(f"Owner-Repo-{sha[:7]}/{name}", data)
    return path


class FakeClient:
    repo_slug = "o/r"

    def __init__(self, zips: dict[str, Path]) -> None:
        self.zips = zips

    def download_snapshot(self, commit, destination, progress=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.zips[commit.sha].read_bytes())
        return destination


def commit(sha: str) -> CommitInfo:
    return CommitInfo(sha, "2026-01-01T00:00:00Z", "m", "https://x")


def fake_prepare(staged, runtime_root, base_python, status):
    (staged / "runtime_python.txt").write_text(sys.executable + "\n")
    return RuntimeResult(Path(sys.executable), "x", False)


class InstallBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths.from_root(self.root / "F")
        self.paths.ensure()
        self.a, self.b = "a" * 40, "b" * 40
        self.zips = {self.a: build_zip(self.root, self.a), self.b: build_zip(self.root, self.b)}
        self.client = FakeClient(self.zips)
        patcher = patch.multiple(T, prepare_runtime=fake_prepare, ensure_base_python=lambda *a, **k: Path(sys.executable))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.updater = DirectGitUpdater(self.paths, LauncherConfig(), lambda _t: None, lambda _w, _t: None)

    def install(self, sha: str):
        return self.updater.install_commit(self.client, commit(sha))

    def test_install_refused_while_another_updater_holds_the_lock(self) -> None:
        with update_lock(self.paths.state), patch.object(DirectGitUpdater, "_health"):
            with self.assertRaises(AlreadyRunningError):
                self.install(self.a)
        self.assertFalse(self.paths.app.exists())

    def test_staged_health_failure_keeps_current_version(self) -> None:
        with patch.object(DirectGitUpdater, "_health"):
            self.install(self.a)
        with patch.object(DirectGitUpdater, "_health", side_effect=ValidationError("staged roto")) as health:
            with self.assertRaises(ValidationError):
                self.install(self.b)
        self.assertEqual(health.call_count, 1)
        self.assertEqual(self.updater.local_commit(), self.a)

    def test_post_swap_health_failure_rolls_back(self) -> None:
        with patch.object(DirectGitUpdater, "_health"):
            self.install(self.a)
        calls = {"n": 0}

        def second_fails(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValidationError("activa rota")

        with patch.object(DirectGitUpdater, "_health", side_effect=second_fails):
            with self.assertRaises(ValidationError):
                self.install(self.b)
        self.assertEqual(self.updater.local_commit(), self.a)
        self.assertFalse(self.paths.app.with_name("App.__previous__").exists())
        self.assertFalse(self.updater.journal.exists())

    def test_backup_retention_is_enforced(self) -> None:
        config = LauncherConfig()
        config.backup_retention = 1
        updater = DirectGitUpdater(self.paths, config, lambda _t: None, lambda _w, _t: None)
        shas = ["c" * 40, "d" * 40, "e" * 40, "f" * 40]
        for sha in shas:
            self.zips[sha] = build_zip(self.root, sha)
        with patch.object(DirectGitUpdater, "_health"):
            for sha in shas:
                updater.install_commit(self.client, commit(sha))
        self.assertEqual(len([p for p in self.paths.rollback.iterdir() if p.is_dir()]), 1)

    def test_git_metadata_is_not_deployed(self) -> None:
        snapshot = self.root / "snap"
        for name in REQUIRED:
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x")
        (snapshot / "GestorWoo/.git").mkdir()
        (snapshot / "GestorWoo/.git/config").write_text("secret")
        (snapshot / "GestorWoo/.env").write_text("TOKEN=1")
        create_runtime(snapshot, self.root / "out", commit="a" * 40, repository="o/r", branch="b", commit_date="", archive_sha256="x")
        self.assertFalse((self.root / "out/GestorWoo/.git").exists())
        self.assertFalse((self.root / "out/GestorWoo/.env").exists())


class MiscRegressionTests(unittest.TestCase):
    def test_symlink_entries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "a.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                info = zipfile.ZipInfo("r/link")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                handle.writestr(info, "/etc/passwd")
            with self.assertRaises(ValidationError):
                safe_extract_snapshot(archive, root / "out")

    def test_short_or_missing_sha_is_rejected(self) -> None:
        client = GitHubClient("o", "r", "main", "tok_en123")
        for payload in ({"sha": "abc"}, {}, []):
            client._json = MagicMock(return_value=payload)  # type: ignore[method-assign]
            with self.subTest(payload=payload), self.assertRaises(DownloadError):
                client.resolve_head()

    def test_draft_and_prerelease_are_ignored(self) -> None:
        client = GitHubClient("o", "r", "main", require_auth=False)
        assets = [
            {"name": "FutonHUB-Launcher.exe", "url": "e"},
            {"name": "FutonHUB-Launcher.exe.sha256", "url": "s"},
        ]
        client._json = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"tag_name": "launcher-v9.0.0", "draft": True, "prerelease": False, "assets": assets},
                {"tag_name": "launcher-v8.0.0", "draft": False, "prerelease": True, "assets": assets},
            ]
        )
        self.assertIsNone(client.latest_launcher_release())


if __name__ == "__main__":
    unittest.main()
