from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from futonhub_auto import flow, python_runtime
from futonhub_auto import transaction as T
from futonhub_auto.config import LauncherConfig
from futonhub_auto.errors import ValidationError
from futonhub_auto.github_api import CommitInfo
from futonhub_auto.paths import AppPaths
from futonhub_auto.python_runtime import RuntimeResult
from futonhub_auto.transaction import DirectGitUpdater

from test_upgrade_regressions import FakeClient, build_zip


SHA = "a" * 40


class Client(FakeClient):
    def __init__(self, zips) -> None:
        super().__init__(zips)

    def resolve_head(self):
        return CommitInfo(SHA, "2026-01-01T00:00:00Z", "msg", "https://x")


def prepare(staged, runtime_root, base_python, status):
    (staged / "runtime_python.txt").write_text(str(base_python) + "\n")
    return RuntimeResult(Path(base_python), "x", False)


class FirstInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths.from_root(self.root / "F")
        self.paths.ensure()
        self.zips = {SHA: build_zip(self.root, SHA)}

    def run_flow(self) -> list[tuple[str, object]]:
        events: list[tuple[str, object]] = []
        started = flow.StartupFlow(
            self.paths,
            LauncherConfig(),
            lambda event, payload: events.append((event, payload)),
            frozen=False,
            client_factory=lambda *a, **k: Client(self.zips),
        )
        started.run("tok_en123")
        return events

    def test_missing_erp_is_installed_automatically_without_errors(self) -> None:
        self.assertFalse((self.paths.app).exists())
        with patch.multiple(T, prepare_runtime=prepare, ensure_base_python=lambda *a, **k: Path(sys.executable)), patch.object(
            DirectGitUpdater, "_health"
        ):
            events = self.run_flow()
        names = [name for name, _ in events]
        self.assertIn("success", names)
        self.assertNotIn("failed", names)
        self.assertNotIn("degraded", names)
        self.assertNotIn("error", names)
        first_state = [p for n, p in events if n == "versions"][0]
        self.assertEqual((first_state.installed_commit, first_state.remote_commit), ("", SHA))
        final_state = [p for n, p in events if n == "success"][0]["state"]
        self.assertEqual(final_state.installed_commit, SHA)
        updater = DirectGitUpdater(self.paths, LauncherConfig(), lambda _t: None, lambda _w, _t: None)
        self.assertEqual(updater.local_commit(), SHA)
        self.assertTrue(updater.installation_ready())
        self.assertFalse(updater.journal.exists())

    def test_system_python_without_tkinter_falls_back_to_managed_python(self) -> None:
        managed = self.root / "managed" / "python.exe"
        managed.parent.mkdir()
        managed.write_text("x")
        calls: list[str] = []

        def health(self, app, python):
            calls.append(str(python))
            if str(python).endswith("system-python"):
                raise ValidationError("No module named tkinter")

        def prepare_with(staged, runtime_root, base_python, status):
            (staged / "runtime_python.txt").write_text(str(base_python) + "\n")
            return RuntimeResult(Path(base_python), "x", False)

        with patch.multiple(
            T,
            prepare_runtime=prepare_with,
            ensure_base_python=lambda *a, **k: self.root / "system-python",
            install_managed_python=lambda *a, **k: managed,
        ), patch.object(DirectGitUpdater, "_health", health):
            events = self.run_flow()
        self.assertIn("success", [name for name, _ in events])
        self.assertTrue(calls[0].endswith("system-python"))
        self.assertEqual(calls[-1], str(managed))

    def test_managed_python_failure_is_reported_not_retried(self) -> None:
        managed = self.paths.runtime / "Python313" / "python.exe"
        managed.parent.mkdir(parents=True)
        managed.write_text("x")
        with patch.multiple(
            T, prepare_runtime=prepare, ensure_base_python=lambda *a, **k: managed
        ), patch.object(DirectGitUpdater, "_health", side_effect=ValidationError("roto")):
            events = self.run_flow()
        self.assertIn("failed", [name for name, _ in events])
        self.assertFalse(self.paths.app.exists())

    def test_python_probe_requires_tkinter_venv_and_ensurepip(self) -> None:
        source = inspect.getsource(python_runtime._valid_python)
        for module in ("tkinter", "venv", "ensurepip"):
            self.assertIn(module, source)


if __name__ == "__main__":
    unittest.main()
