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
        cls = self.window_cls()
        with patch.object(cls, "start_automatic", lambda self: None):
            self.window = cls(self.root, paths, LauncherConfig(), MemoryCredentialStore())

    @staticmethod
    def window_cls():
        from futonhub_auto.gui_compact import LauncherWindow

        return LauncherWindow

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


@unittest.skipIf(tk is None, "tkinter no disponible")
class PalikoGuiSmokeTests(unittest.TestCase):
    """Tres pantallas: Cargando, Todo al día y Problemas con chequeo."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths.from_root(Path(self.temp.name) / "F")
        self.paths.ensure()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"sin entorno gráfico: {exc}")
        self.addCleanup(self.root.destroy)
        from futonhub_auto.gui_paliko import PalikoLauncherWindow

        self.store = MemoryCredentialStore()
        self.cls = PalikoLauncherWindow
        with patch.object(PalikoLauncherWindow, "start_automatic", lambda self: None):
            self.window = PalikoLauncherWindow(self.root, self.paths, LauncherConfig(), self.store)
        self.window.config.auto_open_erp = False

    def pump(self) -> None:
        self.window._drain()
        self.root.update()

    def test_dispatcher_picks_style_by_channel(self) -> None:
        from futonhub_auto import gui
        from futonhub_auto.theme import PALETTE

        self.assertEqual(self.root.cget("bg"), PALETTE.bg)
        with patch.object(gui, "CHANNEL", type("C", (), {"name": "stable"})):
            self.assertEqual(gui.window_class().__name__, "LauncherWindow")
        with patch.object(gui, "CHANNEL", type("C", (), {"name": "test"})):
            self.assertEqual(gui.window_class().__name__, "PalikoLauncherWindow")

    def test_working_view_is_shown_whenever_busy_and_buttons_are_locked(self) -> None:
        w = self.window
        w._show_view("ok")
        w._set_busy(True, "Descargando")
        self.assertEqual(w.view, "working")
        self.assertEqual(w.work_title.get(), "Cargando…")
        for name in ("retry_button", "problem_retry_button", "copy_button", "github_button", "restore_button"):
            self.assertEqual(str(getattr(w, name).cget("state")), "disabled", name)
        w._set_busy(False)
        self.assertEqual(str(w.retry_button.cget("state")), "normal")

    def test_spinner_moves_only_while_working(self) -> None:
        w = self.window
        w._show_view("working")
        before = w._angle
        w._spin()
        self.assertNotEqual(w._angle, before)
        w._show_view("ok")
        frozen = w._angle
        w._spin()
        self.assertEqual(w._angle, frozen)

    def test_success_shows_all_good_screen_and_enables_open(self) -> None:
        from futonhub_auto.versioning import FutonHUBVersionState

        w = self.window
        w._set_busy(True)
        w._post("versions", FutonHUBVersionState("a" * 40, "a" * 40, "0.6.5", "0.6.5"))
        w._post("success", {"message": "listo", "state": FutonHUBVersionState("a" * 40, "a" * 40, "0.6.5", "0.6.5")})
        self.pump()
        self.assertEqual(w.view, "ok")
        self.assertEqual(w.ok_title.get(), "Todo al día")
        self.assertIn("0.6.5", w.ok_sub.get())
        self.assertEqual(str(w.open_button.cget("state")), "normal")

    def test_success_after_changing_commit_says_updated(self) -> None:
        from futonhub_auto.versioning import FutonHUBVersionState

        w = self.window
        w._post("versions", FutonHUBVersionState("a" * 40, "b" * 40, "0.6.4", "0.6.5"))
        w._post("success", {"message": "ok", "state": FutonHUBVersionState("b" * 40, "b" * 40, "0.6.5", "0.6.5")})
        self.pump()
        self.assertEqual(w.ok_title.get(), "Actualizado")

    def test_failure_shows_checklist_with_the_failed_item_and_its_fix(self) -> None:
        w = self.window
        w._post("failed", FailureDecision("token", False, True, "token caducado"))
        self.pump()
        self.assertEqual(w.view, "problem")
        keys = {c.key: c for c in w.problem["checks"]}
        self.assertEqual(keys["github"].status, "fail")
        self.assertEqual(keys["github"].action, "token")
        self.root.update()
        self.assertTrue(w.checks_box.winfo_children())  # se pintaron las filas
        self.assertFalse(w.problem_open_button.winfo_ismapped())  # sin instalación no se puede abrir

    def test_degraded_with_installation_allows_opening_and_waits_for_user_on_token(self) -> None:
        w = self.window
        with patch.object(w, "open_erp") as opened:
            w._post("degraded", FailureDecision("token", True, True, "token caducado"))
            self.pump()
            self.root.update()
        opened.assert_not_called()  # un token caducado no se esconde abriendo el ERP solo
        self.assertEqual(w.view, "problem")
        self.assertTrue(w.problem["ready"])
        self.assertTrue(w.problem_open_button.winfo_ismapped())

    def test_transient_network_problem_opens_installed_erp_automatically(self) -> None:
        w = self.window
        w.config.auto_open_erp = True
        scheduled: list[int] = []
        with patch.object(w.root, "after", side_effect=lambda ms, *a: scheduled.append(ms)):
            w._post("degraded", FailureDecision("network", True, False, "sin red"))
            w._drain()
        self.assertIn(1500, scheduled)

    def test_missing_token_is_a_problem_screen_not_a_dialog(self) -> None:
        w = self.window
        with patch("futonhub_auto.gui_paliko.simpledialog.askstring") as asked:
            PalikoLauncher = self.cls
            PalikoLauncher.start_automatic(w)
        asked.assert_not_called()
        self.assertEqual(w.view, "problem")
        self.assertEqual(w.problem["kind"], "no_token")

    def test_copy_report_puts_technical_report_in_clipboard_without_token(self) -> None:
        w = self.window
        w._secret = "ghp_SECRETO"
        w._append("respuesta con ghp_SECRETO")
        w._post("failed", FailureDecision("rate_limit", False, False, "límite con ghp_SECRETO"))
        self.pump()
        w.copy_report()
        clip = self.root.clipboard_get()
        self.assertIn("INFORME TÉCNICO", clip)
        self.assertIn("Tipo de fallo: rate_limit", clip)
        self.assertNotIn("ghp_SECRETO", clip)
        self.assertIn("copiado", w.copy_note.get())

    def test_erp_crash_shows_problem_with_log_detail_in_report(self) -> None:
        w = self.window
        w._post("erp_closed", (1, Path("x.log"), "Traceback boom"))
        self.pump()
        self.assertEqual(w.view, "problem")
        self.assertEqual(w.problem["kind"], "erp_crash")
        self.assertIn("Traceback boom", w._report_text())
        self.assertFalse(w.problem_open_button.winfo_ismapped())

    def test_admin_panel_hidden_in_worker_mode_and_toggles(self) -> None:
        w = self.window
        self.assertFalse(w.admin_visible)
        self.assertFalse(w.admin_frame.winfo_ismapped())
        w.toggle_admin()
        self.root.update()
        self.assertTrue(w.admin_frame.winfo_ismapped())
        for name in ("github_button", "env_button", "logs_button", "restore_button", "resume_button", "uninstall_button"):
            self.assertTrue(hasattr(w, name), name)


if __name__ == "__main__":
    unittest.main()
