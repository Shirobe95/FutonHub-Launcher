from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from futonhub_auto.config import LauncherConfig
from futonhub_auto.paths import AppPaths
from futonhub_auto.transaction import DirectGitUpdater


class TransactionTests(unittest.TestCase):
    def test_local_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            paths.app.mkdir()
            (paths.app / "SOURCE_COMMIT").write_text("a" * 40)
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            self.assertEqual(updater.local_commit(), "a" * 40)

    def test_invalid_local_commit_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            paths.app.mkdir()
            (paths.app / "SOURCE_COMMIT").write_text("bad")
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            self.assertEqual(updater.local_commit(), "")

    def test_recovery_restores_previous(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            paths.app.mkdir()
            (paths.app / "marker").write_text("new")
            previous = paths.app.with_name("App.__previous__")
            previous.mkdir()
            (previous / "marker").write_text("old")
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            message = updater.recover()
            self.assertIn("restauró", message or "")
            self.assertEqual((paths.app / "marker").read_text(), "old")

class RecoveryPhaseTests(unittest.TestCase):
    def test_postvalidated_recovery_keeps_new_app(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            paths.app.mkdir()
            (paths.app / "marker").write_text("new")
            previous = paths.app.with_name("App.__previous__")
            previous.mkdir()
            (previous / "marker").write_text("old")
            journal = paths.state / "transaction.json"
            journal.write_text(json.dumps({"phase": "postvalidated"}))
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            message = updater.recover()
            self.assertIn("validada", message or "")
            self.assertEqual((paths.app / "marker").read_text(), "new")
            self.assertFalse(previous.exists())

class InstallationReadyTests(unittest.TestCase):
    def test_same_commit_without_runtime_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            (paths.app / "GestorWoo").mkdir(parents=True)
            (paths.app / "Abrir ERP.bat").write_text("x")
            (paths.app / "GestorWoo/gestorwoo.py").write_text("x")
            (paths.app / "SOURCE_COMMIT").write_text("d" * 40)
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            self.assertFalse(updater.installation_ready())

    def test_ready_installation_requires_existing_runtime_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            (paths.app / "GestorWoo").mkdir(parents=True)
            runtime = paths.runtime / "python.exe"
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_text("x")
            (paths.app / "Abrir ERP.bat").write_text("x")
            (paths.app / "GestorWoo/gestorwoo.py").write_text("x")
            (paths.app / "SOURCE_COMMIT").write_text("d" * 40)
            (paths.app / "runtime_python.txt").write_text(str(runtime))
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            self.assertTrue(updater.installation_ready())

    def test_ready_installation_uses_runtime_file_outside_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            (paths.app / "GestorWoo").mkdir(parents=True)
            runtime = paths.runtime / "venvs/hash/Scripts/python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_text("x")
            for relative in ("Abrir ERP.bat", "GestorWoo/gestorwoo.py", "SOURCE_COMMIT"):
                (paths.app / relative).write_text("e" * 40 if relative == "SOURCE_COMMIT" else "x")
            (paths.app / "runtime_python.txt").write_text(str(runtime))
            updater = DirectGitUpdater(paths, LauncherConfig(), lambda _text: None, lambda _written, _total: None)
            self.assertTrue(updater.installation_ready())
            self.assertFalse(str(runtime).startswith(str(paths.app)))

class ManagedRepairTests(unittest.TestCase):
    def test_same_commit_repairs_launcher_owned_entrypoint(self) -> None:
        from unittest.mock import patch
        from futonhub_auto.github_api import CommitInfo
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "x")
            paths.ensure()
            (paths.app / "GestorWoo").mkdir(parents=True)
            runtime = paths.runtime / "python.exe"
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_text("x")
            commit_sha = "f" * 40
            (paths.app / "Abrir ERP.bat").write_text("broken", encoding="ascii")
            (paths.app / "GestorWoo/gestorwoo.py").write_text("x")
            (paths.app / "SOURCE_COMMIT").write_text(commit_sha)
            (paths.app / "runtime_python.txt").write_text(str(runtime))
            updater = DirectGitUpdater(
                paths,
                LauncherConfig(),
                lambda _text: None,
                lambda _written, _total: None,
            )
            commit = CommitInfo(commit_sha, "2026-06-22", "test", "https://example.invalid/archive.zip")
            with patch.object(updater, "_health", return_value=None):
                outcome = updater.install_commit(object(), commit)
            self.assertFalse(outcome.changed)
            self.assertIn("reparados", outcome.message)
            self.assertIn(
                "runtime_python.txt",
                (paths.app / "Abrir ERP.bat").read_text(encoding="ascii"),
            )
