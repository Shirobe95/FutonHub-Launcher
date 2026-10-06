from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import MemoryCredentialStore
from futonhub_auto.flow import FailureDecision
from futonhub_auto.paths import AppPaths

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]


@unittest.skipIf(tk is None, "tkinter no disponible")
class GuiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        paths = AppPaths.from_root(Path(self.temp.name) / "F")
        paths.ensure()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # sin pantalla
            self.skipTest(f"sin entorno gráfico: {exc}")
        self.addCleanup(self.root.destroy)
        from futonhub_auto import gui

        with patch.object(gui.LauncherWindow, "start_automatic", lambda self: None):
            self.window = gui.LauncherWindow(self.root, paths, LauncherConfig(), MemoryCredentialStore())

    def pump(self) -> None:
        self.window._drain()
        self.root.update()

    def test_admin_panel_is_hidden_in_worker_mode_and_has_recovery_actions(self) -> None:
        w = self.window
        self.assertEqual(str(w.open_button.cget("state")), "disabled")
        self.assertFalse(w.admin_visible)
        for name in ("retry_button", "github_button", "env_button", "restore_button", "resume_button", "uninstall_button"):
            self.assertTrue(hasattr(w, name), name)

    def test_success_degraded_and_failure_update_buttons_and_log(self) -> None:
        w = self.window
        w._post("success", {"message": "Listo"})
        self.pump()
        self.assertEqual(str(w.open_button.cget("state")), "normal")
        w.config.auto_open_erp = False
        with patch.object(w, "open_erp"), patch.object(w, "_offer_new_token"):
            w._post("degraded", FailureDecision("token", True, True, "token caducado"))
            self.pump()
        with patch.object(w, "_show_error") as shown, patch.object(w, "_offer_new_token"):
            w._post("failed", FailureDecision("not_found", False, False, "rama borrada"))
            self.pump()
        shown.assert_called_once()
        text = w.log.get("1.0", "end")
        self.assertIn("AVISO: token caducado", text)
        self.assertIn("ERROR: rama borrada", text)

    def test_busy_state_disables_actions(self) -> None:
        w = self.window
        w._set_busy(True, "Descargando")
        for button in (w.retry_button, w.github_button, w.env_button, w.restore_button, w.resume_button):
            self.assertEqual(str(button.cget("state")), "disabled")
        w._set_busy(False)
        self.assertEqual(str(w.retry_button.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main()
