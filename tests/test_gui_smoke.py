from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import MemoryCredentialStore
from futonhub_auto.flow import FailureDecision
from futonhub_auto.paths import AppPaths
from futonhub_auto.theme import PALETTE, STATE_COLORS

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

    def test_palette_and_states_are_consistent(self) -> None:
        for state in ("idle", "working", "ready", "warning", "error"):
            self.assertRegex(STATE_COLORS[state], r"^#[0-9A-Fa-f]{6}$")
        self.assertEqual(self.root.cget("bg"), PALETTE.bg)

    def test_main_actions_exist_and_open_is_disabled_until_ready(self) -> None:
        w = self.window
        self.assertEqual(str(w.open_button.cget("state")), "disabled")
        for name in ("retry_button", "github_button", "env_button", "more_button"):
            self.assertTrue(hasattr(w, name), name)
        labels = [w.more_menu.entrycget(i, "label") for i in range(w.more_menu.index("end") + 1) if w.more_menu.type(i) == "command"]
        self.assertIn("Restaurar versión anterior…", labels)
        self.assertIn("Reanudar actualizaciones", labels)
        self.assertIn("Desinstalar…", labels)

    def test_success_degraded_and_failure_update_headline_and_buttons(self) -> None:
        w = self.window
        w._post("success", "Listo")
        self.pump()
        self.assertEqual(w.headline.get(), "Todo listo")
        self.assertEqual(str(w.open_button.cget("state")), "normal")
        with patch.object(w, "open_erp"), patch.object(w, "_offer_new_token"):
            w._post("degraded", FailureDecision("token", True, True, "token caducado"))
            self.pump()
        self.assertIn("sin comprobar", w.headline.get())
        with patch("futonhub_auto.gui.messagebox.showerror"), patch.object(w, "_offer_new_token"):
            w._post("failed", FailureDecision("not_found", False, False, "rama borrada"))
            self.pump()
        self.assertEqual(w.headline.get(), "Detenido de forma segura")
        text = w.log.get("1.0", "end")
        self.assertIn("AVISO: token caducado", text)
        self.assertIn("ERROR: rama borrada", text)

    def test_busy_state_disables_actions(self) -> None:
        w = self.window
        w._set_busy(True, "Descargando")
        for button in (w.retry_button, w.github_button, w.env_button, w.more_button):
            self.assertEqual(str(button.cget("state")), "disabled")
        w._set_busy(False)
        self.assertEqual(str(w.retry_button.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main()
